"""Enhanced PDF report card with school branding, logo & student photo."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas
from grading import waec_grade, compute_aggregate, aggregate_remark, ordinal, grade_colors as _grade_colors

W, H = A4

def hc(h): return HexColor(h)

def draw_rect(c,x,y,w,h,fill=None,stroke=None,radius=0):
    c.saveState()
    if fill: c.setFillColor(fill)
    if stroke: c.setStrokeColor(stroke)
    else: c.setStrokeColor(hc('#CCCCCC'))
    if radius: c.roundRect(x,y,w,h,radius,fill=1 if fill else 0,stroke=1 if stroke else 0)
    else: c.rect(x,y,w,h,fill=1 if fill else 0,stroke=1 if stroke else 0)
    c.restoreState()

def draw_text(c,text,x,y,font='Helvetica',size=10,color=None,align='left'):
    c.saveState()
    if color: c.setFillColor(color)
    c.setFont(font,size)
    if align=='center': c.drawCentredString(x,y,str(text))
    elif align=='right': c.drawRightString(x,y,str(text))
    else: c.drawString(x,y,str(text))
    c.restoreState()

def generate_report_card(student, scores_data, attendance, remarks,
                          school, class_position_data, output_path, scale=None):
    PRIMARY   = hc(school.get('primary_color','#1B4332'))
    SECONDARY = hc(school.get('secondary_color','#D4A017'))
    LIGHT_BG  = hc('#F0FBF4')
    MUTED     = hc('#64748B')
    DARK      = hc('#1A1A2E')
    MINT      = hc('#95D5B2')

    cv = canvas.Canvas(output_path, pagesize=A4)
    cv.setTitle(f"Report Card - {student.get('first_name','')} {student.get('last_name','')}")

    mx = 14*mm; cw = W - 2*mx

    # ── HEADER ────────────────────────────────────────────────────────────────
    draw_rect(cv,0,H-44*mm,W,44*mm,fill=PRIMARY)

    # Logo
    logo = school.get('logo_path','')
    if logo and os.path.exists(logo):
        try:
            cv.drawImage(logo,mx,H-40*mm,width=28*mm,height=28*mm,
                         preserveAspectRatio=True,mask='auto')
        except: pass
        name_x = mx+32*mm
    else:
        draw_rect(cv,mx,H-40*mm,28*mm,28*mm,fill=SECONDARY)
        draw_text(cv,school.get('short_name','S')[:2].upper(),
                  mx+14*mm,H-29*mm,'Helvetica-Bold',18,PRIMARY,'center')
        name_x = mx+32*mm

    draw_text(cv,school.get('name','School').upper(),
              name_x,H-14*mm,'Helvetica-Bold',15,white)
    draw_text(cv,school.get('address',''),
              name_x,H-20*mm,'Helvetica',8,MINT)
    draw_text(cv,f"Tel: {school.get('phone','')}  |  {school.get('email','')}",
              name_x,H-25.5*mm,'Helvetica',8,MINT)

    # Gold bar
    cv.saveState(); cv.setStrokeColor(SECONDARY); cv.setLineWidth(1.5)
    cv.line(mx,H-30*mm,W-mx,H-30*mm); cv.restoreState()

    draw_text(cv,'STUDENT ACADEMIC REPORT CARD',
              W/2,H-36*mm,'Helvetica-Bold',11,SECONDARY,'center')
    term_map={1:'First Term',2:'Second Term',3:'Third Term'}
    draw_text(cv,f"{term_map.get(school.get('current_term',1),'First Term')}  |  "
              f"Academic Year: {school.get('current_year','')}",
              W/2,H-41*mm,'Helvetica',8,MINT,'center')

    y = H-50*mm

    # ── STUDENT INFO + PHOTO ──────────────────────────────────────────────────
    draw_rect(cv,mx,y-30*mm,cw,30*mm,fill=LIGHT_BG,stroke=MINT)
    draw_rect(cv,mx,y-30*mm,3*mm,30*mm,fill=PRIMARY)

    # Photo box
    photo = student.get('photo_path','')
    ph_x = W - mx - 24*mm; ph_y = y - 28*mm
    if photo and os.path.exists(photo):
        try:
            cv.drawImage(photo,ph_x,ph_y,width=22*mm,height=26*mm,
                         preserveAspectRatio=True,mask='auto')
        except:
            draw_rect(cv,ph_x,ph_y,22*mm,26*mm,fill=hc('#E0E0E0'))
            draw_text(cv,'PHOTO',ph_x+11*mm,ph_y+13*mm,'Helvetica',7,MUTED,'center')
    else:
        draw_rect(cv,ph_x,ph_y,22*mm,26*mm,fill=hc('#E8EAF6'))
        draw_text(cv,'📷',ph_x+11*mm,ph_y+14*mm,'Helvetica',14,MUTED,'center')
        draw_text(cv,'PHOTO',ph_x+11*mm,ph_y+8*mm,'Helvetica',7,MUTED,'center')

    lx=mx+6*mm; rx=mx+cw/2
    draw_text(cv,'STUDENT INFORMATION',lx,y-4*mm,'Helvetica-Bold',8,hc(school.get('primary_color','#1B4332')))
    full_name=f"{student.get('first_name','')} {student.get('last_name','')}"
    fields_l=[('Full Name:',full_name),('Student ID:',student.get('student_id','')),('Date of Birth:',student.get('date_of_birth',''))]
    fields_r=[('Class:',student.get('class_name','')),('Gender:',student.get('gender','')),('Class Teacher:',student.get('class_teacher_name',''))]
    for (lb,vl),(lb2,vl2),ry in zip(fields_l,fields_r,[y-9*mm,y-16*mm,y-23*mm]):
        draw_text(cv,lb,lx,ry,'Helvetica-Bold',8,MUTED)
        draw_text(cv,str(vl),lx+22*mm,ry,'Helvetica',8,DARK)
        draw_text(cv,lb2,rx,ry,'Helvetica-Bold',8,MUTED)
        draw_text(cv,str(vl2),rx+22*mm,ry,'Helvetica',8,DARK)
    y -= 34*mm

    # ── SCORES TABLE ──────────────────────────────────────────────────────────
    draw_text(cv,'▌ ACADEMIC PERFORMANCE',mx+3*mm,y,'Helvetica-Bold',9,PRIMARY)
    y -= 5*mm
    col_w=[cw*p for p in [0.30,0.12,0.12,0.12,0.10,0.11,0.13]]
    hdrs=['Subject','Class\nScore','Exam\nScore','Total\n(100%)','Grade','Points','Remark']
    hh=10*mm
    draw_rect(cv,mx,y-hh,cw,hh,fill=PRIMARY)
    cx=mx
    for hdr,cw_ in zip(hdrs,col_w):
        lines=hdr.split('\n')
        if len(lines)==2:
            draw_text(cv,lines[0],cx+cw_/2,y-4*mm,'Helvetica-Bold',7,white,'center')
            draw_text(cv,lines[1],cx+cw_/2,y-7.5*mm,'Helvetica-Bold',7,white,'center')
        else:
            draw_text(cv,hdr,cx+cw_/2,y-6.5*mm,'Helvetica-Bold',7,white,'center')
        cx+=cw_
    y-=hh

    gc = {}  # populated on demand via grade_colors()
    rh=7.5*mm
    totals=[s['total'] for s in scores_data]
    for i,subj in enumerate(scores_data):
        bg=hc('#F8FFF9') if i%2==0 else white
        draw_rect(cv,mx,y-rh,cw,rh,fill=bg,stroke=hc('#D1E8D8'))
        letter,point,remark_t=waec_grade(subj['total'],scale=scale)
        fg_h,bg_h=_grade_colors(letter)
        row=[(subj['subject_name'],'left'),(f"{subj['class_score']:.1f}",'center'),
             (f"{subj['exam_score']:.1f}",'center'),(f"{subj['total']:.1f}",'center'),
             (letter,'center'),(str(point),'center'),(remark_t,'center')]
        cx=mx
        for j,((val,align),cw_) in enumerate(zip(row,col_w)):
            tx=cx+(2*mm if align=='left' else cw_/2)
            ry2=y-rh/2-1.2*mm
            if j==4:
                draw_rect(cv,cx+1*mm,y-rh+1*mm,cw_-2*mm,rh-2*mm,fill=hc(bg_h))
                draw_text(cv,val,cx+cw_/2,ry2,'Helvetica-Bold',8,hc(fg_h),'center')
            elif j==3: draw_text(cv,val,tx,ry2,'Helvetica-Bold',8,DARK,align)
            else: draw_text(cv,val,tx,ry2,'Helvetica',7.5,DARK,align)
            cx+=cw_
        y-=rh

    grand=sum(s['total'] for s in scores_data)
    agg=compute_aggregate(totals,scale=scale); al,ah=aggregate_remark(agg,scale=scale)
    draw_rect(cv,mx,y-8*mm,cw,8*mm,fill=PRIMARY)
    draw_text(cv,'GRAND TOTAL',mx+2*mm,y-5.5*mm,'Helvetica-Bold',8.5,white)
    draw_text(cv,f"{grand:.1f} / {len(scores_data)*100}",
              mx+sum(col_w[:3])+col_w[3]/2,y-5.5*mm,'Helvetica-Bold',8.5,SECONDARY,'center')
    draw_text(cv,f"Aggregate: {agg if agg else '—'}  ({al})",
              mx+sum(col_w[:4])+2*mm,y-5.5*mm,'Helvetica-Bold',8,SECONDARY)
    y-=8*mm+5*mm

    # ── SUMMARY CARDS ─────────────────────────────────────────────────────────
    draw_text(cv,'▌ PERFORMANCE SUMMARY',mx+3*mm,y,'Helvetica-Bold',9,PRIMARY)
    y-=5*mm
    sw=cw/4-2*mm; sh=18*mm
    items=[
        ('Total Score',f"{grand:.1f}",f"Out of {len(scores_data)*100}",school.get('primary_color','#1B4332')),
        ('Position',ordinal(class_position_data.get('position')),
         f"Out of {class_position_data.get('total_students','—')}",school.get('primary_color','#1B4332')),
        ('Aggregate',str(agg) if agg else '—',al,ah),
        ('Attendance',f"{attendance.get('days_present',0)}/{attendance.get('total_days',0)}",
         f"{attendance.get('days_absent',0)} absent",'#2D6A4F'),
    ]
    for idx,(lbl,val,sub,col) in enumerate(items):
        sx=mx+idx*(sw+2.5*mm)
        draw_rect(cv,sx,y-sh,sw,sh,fill=white,stroke=hc(col))
        draw_rect(cv,sx,y-sh,3*mm,sh,fill=hc(col))
        draw_text(cv,lbl,sx+5*mm,y-5.5*mm,'Helvetica',7.5,MUTED)
        draw_text(cv,val,sx+5*mm,y-11*mm,'Helvetica-Bold',13,hc(col))
        draw_text(cv,sub,sx+5*mm,y-15.5*mm,'Helvetica',7,MUTED)
    y-=sh+5*mm

    # ── CONDUCT & FEE STATUS ──────────────────────────────────────────────────
    draw_rect(cv,mx,y-10*mm,cw,10*mm,fill=LIGHT_BG,stroke=MINT)
    conduct=remarks.get('conduct','Good')
    cc={'Excellent':'#1B4332','Very Good':'#1565C0','Good':'#2D6A4F',
        'Fair':'#E65100','Poor':'#B71C1C'}.get(conduct,'#2D6A4F')
    draw_text(cv,'Conduct:',mx+3*mm,y-6.5*mm,'Helvetica-Bold',8,MUTED)
    draw_text(cv,conduct,mx+20*mm,y-6.5*mm,'Helvetica-Bold',8,hc(cc))
    draw_text(cv,f"Present: {attendance.get('days_present',0)}",mx+50*mm,y-6.5*mm,'Helvetica',8,DARK)
    draw_text(cv,f"Absent: {attendance.get('days_absent',0)}",mx+85*mm,y-6.5*mm,'Helvetica',8,DARK)
    draw_text(cv,f"Total Days: {attendance.get('total_days',0)}",mx+120*mm,y-6.5*mm,'Helvetica',8,DARK)

    # Fee status
    fee_paid=student.get('fee_paid',0); fee_due=student.get('fee_amount',0)
    fee_bal=fee_due-fee_paid
    fee_col='#1B4332' if fee_bal<=0 else '#B71C1C'
    fee_lbl='FEES CLEARED' if fee_bal<=0 else f'BALANCE: GH₵{fee_bal:.2f}'
    draw_text(cv,f"Fees: {fee_lbl}",mx+155*mm,y-6.5*mm,'Helvetica-Bold',8,hc(fee_col))
    y-=14*mm

    # ── REMARKS ───────────────────────────────────────────────────────────────
    draw_text(cv,'▌ REMARKS',mx+3*mm,y,'Helvetica-Bold',9,PRIMARY); y-=5*mm
    hw=cw/2-2*mm; rbh=14*mm
    for bx,title,text in [
        (mx,"Class Teacher's Remark:",remarks.get('class_teacher_remark','')),
        (mx+hw+4*mm,"Head Teacher's Remark:",remarks.get('head_teacher_remark','')),
    ]:
        draw_rect(cv,bx,y-rbh,hw,rbh,fill=LIGHT_BG,stroke=MINT)
        draw_rect(cv,bx,y-rbh,3*mm,rbh,fill=PRIMARY)
        draw_text(cv,title,bx+5*mm,y-4.5*mm,'Helvetica-Bold',7.5,PRIMARY)
        words=text.split(); line=[]; lines_out=[]
        for word in words:
            if len(' '.join(line+[word]))<55: line.append(word)
            else: lines_out.append(' '.join(line)); line=[word]
        if line: lines_out.append(' '.join(line))
        for li,ln in enumerate(lines_out[:2]):
            draw_text(cv,ln,bx+5*mm,y-8.5*mm-li*4.5*mm,'Helvetica',7.5,DARK)
    y-=rbh+5*mm

    # ── SIGNATURES ────────────────────────────────────────────────────────────
    third=cw/3
    for i,(label,name) in enumerate([
        ("Class Teacher",student.get('class_teacher_name','')),
        ("Head Teacher / Principal",""),
        ("Parent / Guardian",student.get('parent_name','')),
    ]):
        sx=mx+i*third
        cv.saveState(); cv.setStrokeColor(PRIMARY); cv.setLineWidth(0.7)
        cv.line(sx+4*mm,y-7*mm,sx+third-4*mm,y-7*mm); cv.restoreState()
        draw_text(cv,label,sx+third/2,y-10*mm,'Helvetica-Bold',7.5,MUTED,'center')
        if name: draw_text(cv,name,sx+third/2,y-14*mm,'Helvetica',7,DARK,'center')
    y-=18*mm

    # ── FOOTER ────────────────────────────────────────────────────────────────
    draw_rect(cv,0,0,W,14*mm,fill=PRIMARY)
    draw_text(cv,school.get('motto',''),W/2,10*mm,'Helvetica-Bold',8,SECONDARY,'center')
    draw_text(cv,f"Next Term Begins: {remarks.get('next_term_begins','')}  |  "
              f"Powered by Lucid IT Hub School System — 0542 361 753",
              W/2,5*mm,'Helvetica',7,MINT,'center')
    cv.save()
    return output_path
