"""Email + SMS bulk sender with progress callbacks."""
import smtplib, os, time, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

def email_body(student_name, school_name, term_label, year, parent_name, agg_label, position):
    return f"""Dear {parent_name or 'Parent/Guardian'},

Greetings from {school_name}!

Please find attached the academic report card for your ward, {student_name},
for the {term_label} of the {year} academic year.

📊 Performance Summary:
   • Overall Remark: {agg_label}
   • Class Position: {position}

We encourage you to review this report with your ward and discuss areas for
improvement as well as celebrate their achievements.

Thank you for your continued support and partnership in education.

Warm regards,
The Management
{school_name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Powered by Lucid IT Hub School System
Contact: 0542 361 753 / 0207 923 981
"""

def send_email(smtp_cfg, to_email, parent_name, student_name,
               pdf_path, school_name, term_label, year, agg_label, position):
    if not to_email or '@' not in to_email:
        return False, 'Invalid email address'
    if not os.path.exists(pdf_path):
        return False, f'PDF not found: {pdf_path}'
    try:
        msg = MIMEMultipart()
        msg['From']    = smtp_cfg['username']
        msg['To']      = to_email
        msg['Subject'] = f"Report Card: {student_name} — {term_label} {year} | {school_name}"
        msg.attach(MIMEText(email_body(student_name, school_name, term_label,
                                        year, parent_name, agg_label, position), 'plain'))
        with open(pdf_path,'rb') as f:
            part = MIMEBase('application','octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
                        f'attachment; filename="{os.path.basename(pdf_path)}"')
        msg.attach(part)
        if smtp_cfg.get('use_tls', True):
            s = smtplib.SMTP(smtp_cfg['host'], smtp_cfg['port'])
            s.ehlo(); s.starttls()
        else:
            s = smtplib.SMTP_SSL(smtp_cfg['host'], smtp_cfg['port'])
        s.login(smtp_cfg['username'], smtp_cfg['password'])
        s.sendmail(smtp_cfg['username'], to_email, msg.as_string())
        s.quit()
        return True, ''
    except smtplib.SMTPAuthenticationError:
        return False, 'Auth failed. Check email/password.'
    except Exception as e:
        return False, str(e)

def send_sms(sms_cfg, phone, message):
    """
    SMS via Hubtel API (Ghana). Requires active Hubtel account.
    For other providers, swap the API call below.
    """
    if not phone:
        return False, 'No phone number'
    try:
        import urllib.request, base64
        # Clean phone number to international format
        phone = phone.strip().replace(' ','').replace('-','')
        if phone.startswith('0'): phone = '233' + phone[1:]
        elif not phone.startswith('233'): phone = '233' + phone

        url = "https://smsc.hubtel.com/v1/messages/send"
        auth = base64.b64encode(
            f"{sms_cfg['api_key']}:{sms_cfg['api_secret']}".encode()
        ).decode()
        data = json.dumps({
            "From": sms_cfg.get('sender_id','SCHOOL'),
            "To": phone,
            "Content": message[:160]
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data,
              headers={'Authorization':f'Basic {auth}',
                       'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200, ''
    except Exception as e:
        return False, str(e)

def sms_message(student_name, school_name, term_label, year, agg_label, position, balance):
    msg = (f"{school_name}: Report card for {student_name} - "
           f"{term_label} {year}. Result: {agg_label}, Position: {position}.")
    if balance and float(balance) > 0:
        msg += f" Fee balance: GH₵{float(balance):.2f}."
    return msg

def bulk_send(smtp_cfg, sms_cfg, jobs, school_name, term_label, year,
              send_email_flag=True, send_sms_flag=False,
              delay=1.5, progress_cb=None):
    results = []
    for i, job in enumerate(jobs):
        if progress_cb: progress_cb(i+1, len(jobs), job['student_name'])
        r = {'student_name':job['student_name'],
             'parent_email':job['parent_email'],
             'db_student_id':job['db_student_id'],
             'email_success':False,'email_error':'',
             'sms_success':False,'sms_error':''}

        if send_email_flag and job.get('parent_email'):
            ok, err = send_email(smtp_cfg, job['parent_email'],
                                  job['parent_name'], job['student_name'],
                                  job['pdf_path'], school_name, term_label, year,
                                  job.get('agg_label','—'), job.get('position','—'))
            r['email_success']=ok; r['email_error']=err

        if send_sms_flag and sms_cfg and sms_cfg.get('is_active') and job.get('parent_phone'):
            msg = sms_message(job['student_name'], school_name, term_label, year,
                              job.get('agg_label','—'), job.get('position','—'),
                              job.get('fee_balance',0))
            ok2, err2 = send_sms(sms_cfg, job['parent_phone'], msg)
            r['sms_success']=ok2; r['sms_error']=err2

        results.append(r)
        if i < len(jobs)-1: time.sleep(delay)
    return results
