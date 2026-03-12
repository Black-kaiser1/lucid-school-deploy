"""Generates a printable class broadsheet — all students, all subjects, one page landscape."""
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from grading import waec_grade, compute_aggregate, aggregate_remark, ordinal, grade_colors as _grade_colors

W, H = landscape(A3)

def hc(h): return HexColor(h)

def generate_broadsheet(school, class_name, students_data, subjects,
                         term, academic_year, output_path, scale=None):
    """
    students_data: list of dicts {name, student_id, scores:{subj_id:total}, attendance, aggregate, position}
    subjects: list of dicts {id, name, code}
    """
    PRIMARY = hc(school.get('primary_color','#1B4332'))
    GOLD    = hc(school.get('secondary_color','#D4A017'))
    LIGHT   = hc('#F0FBF4')
    MUTED   = hc('#64748B')
    DARK    = hc('#1A1A2E')

    cv = canvas.Canvas(output_path, pagesize=landscape(A3))
    cv.setTitle(f"Broadsheet — {class_name} — Term {term} {academic_year}")

    mx=10*mm; my=10*mm

    # Header
    cv.setFillColor(PRIMARY)
    cv.rect(0, H-22*mm, W, 22*mm, fill=1, stroke=0)
    cv.setFont('Helvetica-Bold',14); cv.setFillColor(white)
    cv.drawCentredString(W/2, H-10*mm, school.get('name','School').upper())
    cv.setFont('Helvetica',9); cv.setFillColor(HexColor('#95D5B2'))
    term_map={1:'First Term',2:'Second Term',3:'Third Term'}
    cv.drawCentredString(W/2,H-16*mm,
        f"CLASS BROADSHEET  —  {class_name}  |  {term_map.get(term,'Term')} {academic_year}")

    y = H-26*mm

    # Column layout
    name_w=46*mm; sno_w=8*mm; subj_w=16*mm
    extra_cols=['Total','Agg','Pos','Att','Conduct']
    extra_w=[18*mm,10*mm,10*mm,14*mm,16*mm]

    total_subj_w=subj_w*len(subjects)
    total_extra_w=sum(extra_w)
    table_w=sno_w+name_w+total_subj_w+total_extra_w

    # Header row 1 — group labels
    row1_h=7*mm
    cv.setFillColor(PRIMARY); cv.rect(mx,y-row1_h,table_w,row1_h,fill=1,stroke=0)
    cv.setFont('Helvetica-Bold',7); cv.setFillColor(white)
    cv.drawString(mx+1*mm,y-5*mm,'#')
    cv.drawString(mx+sno_w+1*mm,y-5*mm,'STUDENT NAME')
    sx=mx+sno_w+name_w
    cv.drawCentredString(sx+total_subj_w/2,y-5*mm,'SUBJECT SCORES')
    sx2=sx+total_subj_w
    cv.drawCentredString(sx2+total_extra_w/2,y-5*mm,'SUMMARY')
    y-=row1_h

    # Header row 2 — individual cols
    row2_h=8*mm
    cv.setFillColor(HexColor('#2D6A4F')); cv.rect(mx,y-row2_h,table_w,row2_h,fill=1,stroke=0)
    cv.setFont('Helvetica-Bold',6.5); cv.setFillColor(white)
    cv.drawCentredString(mx+sno_w/2,y-5.5*mm,'#')
    cv.drawString(mx+sno_w+1*mm,y-5.5*mm,'Name')
    sx=mx+sno_w+name_w
    for subj in subjects:
        cv.drawCentredString(sx+subj_w/2,y-4*mm,subj['code'][:5])
        sx+=subj_w
    for col,ew in zip(extra_cols,extra_w):
        cv.drawCentredString(sx+ew/2,y-5.5*mm,col)
        sx+=ew
    y-=row2_h

    # Data rows
    row_h=7*mm
    conduct_short={'Excellent':'Exc.','Very Good':'V.Good','Good':'Good',
                   'Fair':'Fair','Poor':'Poor'}
    for i,stu in enumerate(students_data):
        bg=hc('#F8FFF9') if i%2==0 else white
        cv.setFillColor(bg); cv.rect(mx,y-row_h,table_w,row_h,fill=1,stroke=0)
        cv.setStrokeColor(hc('#D1E8D8')); cv.setLineWidth(0.3)
        cv.rect(mx,y-row_h,table_w,row_h,fill=0,stroke=1)

        cv.setFont('Helvetica',6.5); cv.setFillColor(DARK)
        cv.drawCentredString(mx+sno_w/2,y-4.8*mm,str(i+1))
        cv.drawString(mx+sno_w+1*mm,y-4.8*mm,stu['name'][:30])

        sx=mx+sno_w+name_w
        for subj in subjects:
            total=stu['scores'].get(subj['id'],0)
            letter,_,_=waec_grade(total,scale=scale)
            fg_h,bg_h=_grade_colors(letter)
            cv.setFillColor(hc(bg_h)); cv.rect(sx+0.5*mm,y-row_h+0.5*mm,
                subj_w-1*mm,row_h-1*mm,fill=1,stroke=0)
            cv.setFont('Helvetica',6.5); cv.setFillColor(hc(fg_h))
            cv.drawCentredString(sx+subj_w/2,y-4.8*mm,str(int(total)) if total else '—')
            sx+=subj_w

        # Summary cols
        cv.setFont('Helvetica-Bold',7); cv.setFillColor(DARK)
        total_score=stu.get('total_score',0)
        cv.drawCentredString(sx+extra_w[0]/2,y-4.8*mm,f"{total_score:.0f}"); sx+=extra_w[0]
        agg=stu.get('aggregate'); al,ah=aggregate_remark(agg,scale=scale)
        cv.setFillColor(hc(ah))
        cv.drawCentredString(sx+extra_w[1]/2,y-4.8*mm,str(agg) if agg else '—'); sx+=extra_w[1]
        cv.setFillColor(DARK)
        cv.drawCentredString(sx+extra_w[2]/2,y-4.8*mm,ordinal(stu.get('position'))); sx+=extra_w[2]
        att=stu.get('attendance',{})
        att_str=f"{att.get('days_present',0)}/{att.get('total_days',0)}"
        cv.setFont('Helvetica',6.5)
        cv.drawCentredString(sx+extra_w[3]/2,y-4.8*mm,att_str); sx+=extra_w[3]
        cond=conduct_short.get(stu.get('conduct','Good'),'Good')
        cv.drawCentredString(sx+extra_w[4]/2,y-4.8*mm,cond)
        y-=row_h

    # Class averages row
    cv.setFillColor(PRIMARY); cv.rect(mx,y-row_h,table_w,row_h,fill=1,stroke=0)
    cv.setFont('Helvetica-Bold',7); cv.setFillColor(white)
    cv.drawString(mx+sno_w+1*mm,y-4.8*mm,'CLASS AVERAGE')
    sx=mx+sno_w+name_w
    for subj in subjects:
        scores=[s['scores'].get(subj['id'],0) for s in students_data]
        avg=sum(scores)/len(scores) if scores else 0
        cv.drawCentredString(sx+subj_w/2,y-4.8*mm,f"{avg:.1f}")
        sx+=subj_w
    avg_total=sum(s.get('total_score',0) for s in students_data)/len(students_data) if students_data else 0
    cv.setFillColor(HexColor('#D4A017'))
    cv.drawCentredString(sx+extra_w[0]/2,y-4.8*mm,f"{avg_total:.1f}")

    # Footer
    cv.setFillColor(PRIMARY); cv.rect(0,0,W,10*mm,fill=1,stroke=0)
    cv.setFont('Helvetica',7); cv.setFillColor(HexColor('#95D5B2'))
    cv.drawCentredString(W/2,6*mm,
        f"Generated by Lucid IT Hub School Management System  |  {school.get('name','')}  |  0542 361 753")
    cv.drawCentredString(W/2,3*mm,f"Total Students: {len(students_data)}  |  {term_map.get(term,'Term')}  |  {academic_year}")

    cv.save()
    return output_path
