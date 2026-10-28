from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, SQLModel
import csv, io, json, os
from .database import create_db_and_tables, get_session, engine
from .models import Officer, Institution, Complaint, CaseAction, OverlapAlert, CoordinationRecord, Notification, AuditLog
from .security import hash_password, verify_password, create_token, decode_token

app = FastAPI(title="AICTE Complaint Monitoring API", version="1.0.0")
origins = [os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

STATUSES = ["Received", "Pending", "Under Process", "Transferred", "Escalated", "Disposed"]
ACTIVE = ["Received", "Pending", "Under Process", "Transferred", "Escalated"]

@app.on_event("startup")
def startup():
    create_db_and_tables()

def current_user(authorization: Optional[str] = Header(default=None), session: Session = Depends(get_session)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in.")
    email = decode_token(authorization.split(" ", 1)[1])
    if not email:
        raise HTTPException(401, "Session expired. Please sign in again.")
    user = session.exec(select(Officer).where(Officer.email == email, Officer.is_active == True)).first()
    if not user:
        raise HTTPException(401, "User is not active or does not exist.")
    return user

def log_action(session, user, action, entity_type, entity_id="", details=""):
    session.add(AuditLog(user_email=user.email if user else "system", action=action, entity_type=entity_type, entity_id=str(entity_id), details=details))

def institution_dict(session, inst):
    cases = session.exec(select(Complaint).where(Complaint.institution_id == inst.id)).all()
    active = [c for c in cases if c.current_status in ACTIVE]
    overdue = [c for c in active if c.expected_disposal_at and c.expected_disposal_at < date.today()]
    alerts = session.exec(select(OverlapAlert).where(OverlapAlert.institution_id == inst.id, OverlapAlert.review_status.in_(["New", "Under Review", "Coordination Required"]))).all()
    return {**inst.model_dump(), "total_cases": len(cases), "active_cases": len(active), "overdue_cases": len(overdue), "active_alerts": len(alerts), "last_complaint_date": max([str(c.received_at) for c in cases], default=None)}

def complaint_dict(session, c):
    inst = session.get(Institution, c.institution_id)
    return {**c.model_dump(), "institution_name": inst.name if inst else "Unknown institution",
            "overdue": bool(c.current_status != "Disposed" and c.expected_disposal_at and c.expected_disposal_at < date.today()),
            "age_days": (date.today() - c.received_at).days}

@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.exec(select(Officer.id).limit(1)).all()
    return {"status": "ok", "database": "connected", "demo_mode": True}

@app.post("/api/auth/login")
def login(payload: dict, session: Session = Depends(get_session)):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    user = session.exec(select(Officer).where(Officer.email == email)).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    return {"access_token": create_token(user.email), "token_type": "bearer",
            "user": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role, "bureau": user.bureau}}

@app.get("/api/auth/me")
def me(user: Officer = Depends(current_user)):
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role, "bureau": user.bureau}

@app.get("/api/dashboard/summary")
def dashboard_summary(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    cases = session.exec(select(Complaint)).all()
    alerts = session.exec(select(OverlapAlert)).all()
    active_alerts = [a for a in alerts if a.review_status in ["New", "Under Review", "Coordination Required"]]
    return {"total_cases": len(cases), "pending_cases": sum(c.current_status == "Pending" for c in cases),
            "under_process": sum(c.current_status == "Under Process" for c in cases),
            "disposed_cases": sum(c.current_status == "Disposed" for c in cases),
            "transferred_cases": sum(c.current_status == "Transferred" for c in cases),
            "overdue_cases": sum(c.current_status != "Disposed" and c.expected_disposal_at and c.expected_disposal_at < date.today() for c in cases),
            "active_overlap_alerts": len(active_alerts), "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}

@app.get("/api/dashboard/charts")
def dashboard_charts(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    cases = session.exec(select(Complaint)).all()
    statuses = {s: sum(c.current_status == s for c in cases) for s in STATUSES}
    bureaus = {}
    for c in cases: bureaus[c.current_bureau] = bureaus.get(c.current_bureau, 0) + 1
    trends = {}
    for c in cases:
        key = c.received_at.strftime("%Y-%m")
        trends[key] = trends.get(key, 0) + 1
    return {"status_distribution": [{"name": k, "value": v} for k,v in statuses.items()],
            "bureau_workload": [{"name": k, "cases": v} for k,v in bureaus.items()],
            "monthly_received": [{"month": k, "received": v} for k,v in sorted(trends.items())]}

@app.get("/api/institutions")
def list_institutions(q: str = "", state: str = "", page: int = 1, page_size: int = 20,
                      session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    statement = select(Institution)
    if q: statement = statement.where((Institution.name.contains(q)) | (Institution.institution_code.contains(q)) | (Institution.state.contains(q)))
    if state: statement = statement.where(Institution.state == state)
    rows = session.exec(statement.order_by(Institution.name).offset((page-1)*page_size).limit(min(page_size,100))).all()
    return {"items": [institution_dict(session, i) for i in rows], "page": page, "page_size": page_size}

@app.post("/api/institutions")
def create_institution(payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    if user.role != "Administrator": raise HTTPException(403, "Administrator role required.")
    name = str(payload.get("name", "")).strip()
    code = str(payload.get("institution_code", "")).strip().upper()
    if not name or not code: raise HTTPException(422, "Institution name and internal code are required.")
    if session.exec(select(Institution).where(Institution.institution_code == code)).first(): raise HTTPException(409, "Institution code already exists.")
    aid = str(payload.get("aicte_permanent_id", "")).strip() or None
    if aid and session.exec(select(Institution).where(Institution.aicte_permanent_id == aid)).first(): raise HTTPException(409, "AICTE Permanent ID already exists.")
    inst = Institution(institution_code=code, aicte_permanent_id=aid, name=name, address=payload.get("address",""), state=payload.get("state","Madhya Pradesh"), district=payload.get("district",""), region=payload.get("region","Central"), institution_type=payload.get("institution_type","Engineering College"))
    session.add(inst); session.commit(); session.refresh(inst)
    log_action(session,user,"CREATE","Institution",inst.id,name); session.commit()
    return institution_dict(session, inst)

@app.get("/api/institutions/{institution_id}")
def get_institution(institution_id: int, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    inst = session.get(Institution, institution_id)
    if not inst: raise HTTPException(404, "Institution not found.")
    return institution_dict(session, inst)

@app.patch("/api/institutions/{institution_id}")
def update_institution(institution_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    if user.role != "Administrator": raise HTTPException(403, "Administrator role required.")
    inst = session.get(Institution, institution_id)
    if not inst: raise HTTPException(404, "Institution not found.")
    for key in ["name","address","state","district","region","institution_type","is_active"]:
        if key in payload: setattr(inst,key,payload[key])
    session.add(inst); log_action(session,user,"UPDATE","Institution",inst.id,json.dumps(payload)); session.commit(); session.refresh(inst)
    return institution_dict(session, inst)

@app.get("/api/complaints")
def list_complaints(q: str = "", status: str = "", bureau: str = "", overdue_only: bool = False,
                    page: int = 1, page_size: int = 20, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    statement = select(Complaint)
    if status: statement = statement.where(Complaint.current_status == status)
    if bureau: statement = statement.where(Complaint.current_bureau == bureau)
    if q:
        ids = [i.id for i in session.exec(select(Institution).where(Institution.name.contains(q) | Institution.institution_code.contains(q))).all()]
        statement = statement.where((Complaint.case_id.contains(q)) | (Complaint.title.contains(q)) | (Complaint.institution_id.in_(ids or [-1])))
    rows = session.exec(statement.order_by(Complaint.received_at.desc()).offset((page-1)*page_size).limit(min(page_size,100))).all()
    result = [complaint_dict(session,c) for c in rows]
    if overdue_only: result = [c for c in result if c["overdue"]]
    return {"items": result, "page": page, "page_size": page_size}

@app.post("/api/complaints")
def create_complaint(payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    inst = session.get(Institution, payload.get("institution_id"))
    if not inst: raise HTTPException(422, "Choose an existing institution.")
    title = str(payload.get("title","")).strip()
    description = str(payload.get("description","")).strip()
    if not title or not description: raise HTTPException(422, "Title and description are required.")
    next_num = (session.exec(select(Complaint.id).order_by(Complaint.id.desc()).limit(1)).first() or 0) + 1
    case_id = f"CASE-{date.today().year}-{next_num:04d}"
    c = Complaint(case_id=case_id, institution_id=inst.id, title=title, description=description,
        category=payload.get("category","Other"), source=payload.get("source","Online"),
        received_at=date.fromisoformat(payload["received_at"]) if payload.get("received_at") else date.today(),
        current_status=payload.get("current_status","Received"), priority=payload.get("priority","Normal"),
        current_bureau=payload.get("current_bureau","Regulation Bureau (RB)"),
        assigned_officer=payload.get("assigned_officer","Unassigned"),
        expected_disposal_at=date.fromisoformat(payload["expected_disposal_at"]) if payload.get("expected_disposal_at") else None)
    session.add(c); session.commit(); session.refresh(c)
    session.add(CaseAction(complaint_id=c.id, officer_name=user.full_name, action_type="Complaint received", remarks="Case registered", new_status=c.current_status))
    session.add(Notification(notification_type="New case", message=f"{c.case_id} was registered for {inst.name}.", related_case=c.case_id))
    log_action(session,user,"CREATE","Complaint",c.case_id,title); session.commit()
    return complaint_dict(session,c)

@app.get("/api/complaints/{complaint_id}")
def get_complaint(complaint_id: int, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    c = session.get(Complaint, complaint_id)
    if not c: raise HTTPException(404, "Complaint not found.")
    return complaint_dict(session,c)

@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    c = session.get(Complaint, complaint_id)
    if not c: raise HTTPException(404, "Complaint not found.")
    allowed = {"title","description","category","priority","expected_disposal_at","assigned_officer","current_bureau"}
    previous_status = c.current_status
    for key in allowed:
        if key in payload:
            val = payload[key]
            if key == "expected_disposal_at" and val: val = date.fromisoformat(val)
            setattr(c,key,val)
    if "current_status" in payload:
        new_status = payload["current_status"]
        transitions = {"Received":["Pending","Under Process"],"Pending":["Under Process","Escalated","Transferred"],"Under Process":["Pending","Escalated","Transferred","Disposed"],"Transferred":["Under Process","Pending","Escalated","Disposed"],"Escalated":["Under Process","Disposed"],"Disposed":[]}
        if new_status not in transitions.get(c.current_status, []): raise HTTPException(422, f"Invalid status transition: {c.current_status} to {new_status}.")
        c.current_status = new_status
        if new_status == "Disposed": c.disposed_at = date.today()
        session.add(CaseAction(complaint_id=c.id, officer_name=user.full_name, action_type="Status updated", previous_status=previous_status, new_status=new_status))
    session.add(c); log_action(session,user,"UPDATE","Complaint",c.case_id,json.dumps(payload)); session.commit(); session.refresh(c)
    return complaint_dict(session,c)

@app.post("/api/complaints/{complaint_id}/transfer")
def transfer_complaint(complaint_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    c = session.get(Complaint, complaint_id)
    if not c: raise HTTPException(404, "Complaint not found.")
    new_bureau = str(payload.get("bureau","")).strip()
    if not new_bureau: raise HTTPException(422, "Target Bureau is required.")
    old = c.current_bureau; old_status = c.current_status
    c.current_bureau = new_bureau; c.current_status = "Transferred"
    if payload.get("assigned_officer"): c.assigned_officer = payload["assigned_officer"]
    session.add(c); session.add(CaseAction(complaint_id=c.id, officer_name=user.full_name, action_type="Case transferred", remarks=payload.get("remarks",""), previous_status=old_status, new_status="Transferred"))
    log_action(session,user,"TRANSFER","Complaint",c.case_id,f"{old} -> {new_bureau}"); session.commit(); session.refresh(c)
    return complaint_dict(session,c)

@app.post("/api/complaints/{complaint_id}/actions")
def add_case_action(complaint_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    c = session.get(Complaint, complaint_id)
    if not c: raise HTTPException(404, "Complaint not found.")
    remarks = str(payload.get("remarks","")).strip()
    if not remarks: raise HTTPException(422, "Enter a remark.")
    action = CaseAction(complaint_id=c.id, officer_name=user.full_name, action_type=payload.get("action_type","Remark added"), remarks=remarks)
    session.add(action); log_action(session,user,"ADD_REMARK","Complaint",c.case_id,remarks); session.commit(); session.refresh(action)
    return action

@app.get("/api/complaints/{complaint_id}/history")
def complaint_history(complaint_id: int, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    if not session.get(Complaint, complaint_id): raise HTTPException(404, "Complaint not found.")
    return session.exec(select(CaseAction).where(CaseAction.complaint_id == complaint_id).order_by(CaseAction.created_at.desc())).all()

@app.get("/api/overlaps")
def list_overlaps(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    rows = session.exec(select(OverlapAlert).order_by(OverlapAlert.created_at.desc())).all()
    return {"items": [{**a.model_dump(), "institution_name": (session.get(Institution,a.institution_id).name if session.get(Institution,a.institution_id) else "Unknown")} for a in rows]}

@app.post("/api/overlaps/scan")
def scan_overlaps(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    cases = session.exec(select(Complaint).where(Complaint.current_status != "Disposed")).all()
    by_inst = {}
    for c in cases: by_inst.setdefault(c.institution_id, []).append(c)
    created = 0
    for inst_id, group in by_inst.items():
        bureaus = {c.current_bureau for c in group}
        if len(group) < 2 or len(bureaus) < 2: continue
        ids = sorted(c.id for c in group)
        signature = ",".join(map(str,ids))
        existing = session.exec(select(OverlapAlert).where(OverlapAlert.institution_id == inst_id, OverlapAlert.case_ids == signature, OverlapAlert.review_status.in_(["New","Under Review","Coordination Required"]))).first()
        if not existing:
            session.add(OverlapAlert(institution_id=inst_id, case_ids=signature, explanation=f"{len(group)} active complaints across {len(bureaus)} bureaus. Same institution is a review signal, not proof of duplication.", alert_type="Cross-bureau institution overlap"))
            created += 1
    if created: log_action(session,user,"SCAN","OverlapAlert","",f"Created {created} alerts")
    session.commit()
    return {"created":created,"message":f"Overlap scan complete. {created} new alert(s) created."}

@app.post("/api/overlaps/{alert_id}/review")
def review_overlap(alert_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    alert = session.get(OverlapAlert,alert_id)
    if not alert: raise HTTPException(404,"Alert not found.")
    status = payload.get("review_status")
    allowed = ["Under Review","Confirmed Related","Confirmed Duplicate","Not Related","Coordination Required","Resolved"]
    if status not in allowed: raise HTTPException(422,"Unsupported review status.")
    alert.review_status = status; alert.resolution_remarks = str(payload.get("remarks",""))
    session.add(alert); log_action(session,user,"REVIEW","OverlapAlert",alert.id,status); session.commit(); session.refresh(alert)
    return alert

@app.get("/api/coordination")
def list_coordination(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    rows = session.exec(select(CoordinationRecord).order_by(CoordinationRecord.created_at.desc())).all()
    return {"items":[{**r.model_dump(),"institution_name":(session.get(Institution,r.institution_id).name if session.get(Institution,r.institution_id) else "Unknown")} for r in rows]}

@app.post("/api/coordination")
def create_coordination(payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    inst = session.get(Institution,payload.get("institution_id"))
    if not inst: raise HTTPException(422,"Select an existing institution.")
    n = (session.exec(select(CoordinationRecord.id).order_by(CoordinationRecord.id.desc()).limit(1)).first() or 0)+1
    r = CoordinationRecord(coordination_code=f"COORD-{date.today().year}-{n:04d}",institution_id=inst.id,linked_cases=str(payload.get("linked_cases","")),reason=payload.get("reason",""),owner=payload.get("owner",user.full_name),next_action=payload.get("next_action","Review linked cases"),due_at=date.fromisoformat(payload["due_at"]) if payload.get("due_at") else None)
    session.add(r); log_action(session,user,"CREATE","CoordinationRecord",r.coordination_code,r.reason); session.commit(); session.refresh(r)
    return r

@app.patch("/api/coordination/{coordination_id}")
def update_coordination(coordination_id: int, payload: dict, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    r=session.get(CoordinationRecord,coordination_id)
    if not r: raise HTTPException(404,"Coordination record not found.")
    for key in ["owner","reason","status","next_action"]:
        if key in payload: setattr(r,key,payload[key])
    if "due_at" in payload: r.due_at=date.fromisoformat(payload["due_at"]) if payload["due_at"] else None
    session.add(r); log_action(session,user,"UPDATE","CoordinationRecord",r.coordination_code,json.dumps(payload)); session.commit(); session.refresh(r)
    return r

@app.get("/api/notifications")
def notifications(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    rows=session.exec(select(Notification).order_by(Notification.created_at.desc())).all()
    return {"items":rows}

@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    n=session.get(Notification,notification_id)
    if not n: raise HTTPException(404,"Notification not found.")
    n.is_read=True; session.add(n); session.commit(); return n

@app.post("/api/notifications/read-all")
def read_all_notifications(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    rows=session.exec(select(Notification).where(Notification.is_read == False)).all()
    for n in rows: n.is_read=True; session.add(n)
    session.commit(); return {"updated":len(rows)}

@app.get("/api/bureaus")
def bureaus(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    cases=session.exec(select(Complaint)).all()
    names=sorted(set([c.current_bureau for c in cases]+["Regulation Bureau (RB)","Public Grievance Redressal Cell (PGRC)","Other Bureau","Regional Office"]))
    return {"items":[{"name":n,"total_cases":sum(c.current_bureau==n for c in cases),"active_cases":sum(c.current_bureau==n and c.current_status in ACTIVE for c in cases),"overdue_cases":sum(c.current_bureau==n and c.current_status in ACTIVE and c.expected_disposal_at and c.expected_disposal_at<date.today() for c in cases)} for n in names]}

@app.get("/api/reports/summary")
def report_summary(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    cases=session.exec(select(Complaint)).all()
    durations=[(c.disposed_at-c.received_at).days for c in cases if c.disposed_at]
    age_buckets={"0-7 days":0,"8-15 days":0,"16-30 days":0,"31-60 days":0,"More than 60 days":0}
    for c in cases:
        if c.current_status=="Disposed": continue
        age=(date.today()-c.received_at).days
        bucket="0-7 days" if age<=7 else "8-15 days" if age<=15 else "16-30 days" if age<=30 else "31-60 days" if age<=60 else "More than 60 days"
        age_buckets[bucket]+=1
    return {"case_ageing":[{"name":k,"value":v} for k,v in age_buckets.items()],"average_disposal_days":round(sum(durations)/len(durations),1) if durations else None,"disposed_count":len(durations),"total_cases":len(cases)}

@app.get("/api/reports/export.csv")
def export_csv(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(["Case ID","Institution","Category","Received","Bureau","Officer","Status","Expected disposal","Priority"])
    for c in session.exec(select(Complaint).order_by(Complaint.received_at.desc())).all():
        inst=session.get(Institution,c.institution_id)
        writer.writerow([c.case_id,inst.name if inst else "",c.category,c.received_at,c.current_bureau,c.assigned_officer,c.current_status,c.expected_disposal_at or "",c.priority])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=complaints-report.csv"})

@app.get("/api/audit")
def audit_log(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    if user.role != "Administrator": raise HTTPException(403,"Administrator role required.")
    return {"items":session.exec(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(300)).all()}

@app.get("/api/officers")
def officers(session: Session = Depends(get_session), user: Officer = Depends(current_user)):
    return {"items":[{"id":o.id,"full_name":o.full_name,"email":o.email,"role":o.role,"bureau":o.bureau,"region":o.region,"is_active":o.is_active} for o in session.exec(select(Officer)).all()]}

@app.get("/api/settings")
def get_settings(user: Officer = Depends(current_user)):
    return {"demo_mode":True,"ai_similarity_available":False,"ai_similarity_note":"Rule-based cross-bureau detection is active. Semantic model is not configured.","deadline_reminders_days":[7,3,1],"statuses":STATUSES,"categories":["Fee Refund","Admission","Faculty","Infrastructure","Regulatory Compliance","Examination","Scholarship","Other"]}

