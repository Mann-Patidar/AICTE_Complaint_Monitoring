from datetime import date, timedelta
from sqlmodel import Session, select
from .database import create_db_and_tables, engine
from .models import Officer, Institution, Complaint, CaseAction, OverlapAlert, CoordinationRecord, Notification
from .security import hash_password

def seed():
    create_db_and_tables()
    with Session(engine) as s:
        if not s.exec(select(Officer).where(Officer.email=="admin@demo.local")).first():
            s.add(Officer(full_name="Demo Administrator",email="admin@demo.local",password_hash=hash_password("Demo@12345"),role="Administrator",bureau="Administration"))
        bureaus=["Regulation Bureau (RB)","Public Grievance Redressal Cell (PGRC)","Other Bureau","Regional Office"]
        insts=[]
        for i in range(1,26):
            code=f"DEMO-{i:03d}"
            inst=s.exec(select(Institution).where(Institution.institution_code==code)).first()
            if not inst:
                inst=Institution(institution_code=code,aicte_permanent_id=f"DEMO-ID-{i:04d}",name=f"{['Central','National','Western','Riverdale','Pioneer'][i%5]} {['Institute of Technology','Engineering College','Technical University','College of Engineering','School of Applied Sciences'][i%5]} {i:02d}",address=f"{i} Demonstration Road",state=["Madhya Pradesh","Maharashtra","Rajasthan","Gujarat","Uttar Pradesh"][i%5],district=["Bhopal","Indore","Pune","Jaipur","Lucknow"][i%5],region=["Central","West","North"][i%3])
                s.add(inst); s.commit(); s.refresh(inst)
            insts.append(inst)
        s.commit()
        existing=s.exec(select(Complaint)).first()
        if not existing:
            categories=["Fee Refund","Admission","Faculty","Infrastructure","Regulatory Compliance","Examination","Scholarship","Other"]
            statuses=["Received","Pending","Under Process","Transferred","Escalated","Disposed"]
            for i in range(1,121):
                inst=insts[(i-1)%len(insts)]
                status=statuses[i%len(statuses)]
                received=date.today()-timedelta(days=(i*3)%120)
                due=received+timedelta(days=30)
                c=Complaint(case_id=f"CASE-{date.today().year}-{i:04d}",institution_id=inst.id,title=f"{categories[i%len(categories)]} concern at {inst.name}",description=f"Demonstration complaint concerning {categories[i%len(categories)].lower()}. This record is fictional and intended only for testing case tracking and coordination workflows.",category=categories[i%len(categories)],received_at=received,current_status=status,priority=["Low","Normal","High","Urgent"][i%4],current_bureau=bureaus[i%len(bureaus)],assigned_officer=["A. Sharma","R. Verma","S. Khan","Unassigned"][i%4],expected_disposal_at=due,disposed_at=received+timedelta(days=18) if status=="Disposed" else None)
                s.add(c)
            s.commit()
            all_cases=s.exec(select(Complaint)).all()
            for c in all_cases[:45]:
                s.add(CaseAction(complaint_id=c.id,officer_name="Demo Officer",action_type="Status updated",remarks="Fictional seed history",new_status=c.current_status))
            s.add(Notification(notification_type="Deadline reminder",message="A demonstration case is approaching its expected disposal date."))
            s.add(Notification(notification_type="Cross-bureau alert",message="Potential cross-bureau overlap needs human review."))
            s.commit()
        # A first scan will generate overlap alerts from real seeded case data.
        print("Seed complete. Login: admin@demo.local / Demo@12345")
if __name__=="__main__": seed()
