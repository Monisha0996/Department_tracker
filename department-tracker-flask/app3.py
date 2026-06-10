import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = "my-task-app-secret-key-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR,'app.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ------------- Models -------------
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")  # 'admin' or 'user'
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=True)
    department = db.relationship("Department", backref="users")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False)
    department = db.relationship("Department", backref="tasks")
    assignee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    assigner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigner = db.relationship("User", foreign_keys=[assigner_id])
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="OPEN")  # OPEN, IN_PROGRESS, COMPLETED, REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TaskUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    task = db.relationship("Task", backref=db.backref("updates", order_by="TaskUpdate.created_at.desc()"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User")
    status = db.Column(db.String(20), default="COMMENT")  # COMMENT, PROOF, COMPLETED, REJECTED
    comment = db.Column(db.Text, nullable=True)
    attachment_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ------------- Utility -------------
def require_admin():
    if not current_user.is_authenticated or current_user.role != "admin":
        abort(403)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"png","jpg","jpeg","pdf","doc","docx","xlsx","ppt","pptx","txt","csv","zip"}

# ------------- Routes -------------
@app.route("/admin")
@login_required
def admin():
    require_admin()
    return redirect(url_for("index"))


@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        dept_id = request.form.get("department_id")

        # Basic validation
        if not name or not email or not password:
            flash("All fields are required","danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered","warning")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            role="user",
            department_id=int(dept_id) if dept_id else None
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Account created! Please login.","success")
        return redirect(url_for("login"))

    return render_template(
        "register.html",
        departments=Department.query.order_by(Department.name).all()
    )


@app.route("/")
@login_required
def index():
    # Admin sees all; user sees their department + assignments
    if current_user.role == "admin":
        tasks = Task.query.order_by(Task.created_at.desc()).all()
    else:
        tasks = Task.query.filter(
            (Task.assignee_id == current_user.id) | (Task.department_id == current_user.department_id)
        ).order_by(Task.created_at.desc()).all()
    return render_template("dashboard.html", tasks=tasks)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        pw = request.form.get("password","")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(pw):
            login_user(user)
            return redirect(url_for("index"))
        flash("Invalid credentials","danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/setup", methods=["GET","POST"])
def setup():
    # Simple one-time setup to create admin and a sample department/user
    if User.query.first():
        return redirect(url_for("login"))
    if request.method == "POST":
        school = Department(name=request.form.get("dept","Operations"))
        db.session.add(school)
        admin = User(name="Admin", email=request.form["email"].lower(), role="admin", department=school)
        admin.set_password(request.form["password"])
        db.session.add(admin)
        db.session.commit()
        flash("Setup complete. Please login.","success")
        return redirect(url_for("login"))
    return render_template("setup.html")

@app.route("/departments", methods=["GET","POST"])
@login_required
def departments():
    require_admin()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if name:
            if Department.query.filter_by(name=name).first():
                flash("Department already exists","warning")
            else:
                db.session.add(Department(name=name))
                db.session.commit()
                flash("Department added","success")
        return redirect(url_for("departments"))
    return render_template("departments.html", departments=Department.query.order_by(Department.name).all())

@app.route("/users", methods=["GET","POST"])
@login_required
def users():
    require_admin()
    if request.method == "POST":
        name = request.form.get("name").strip()
        email = request.form.get("email").strip().lower()
        dept_id = int(request.form.get("department_id"))
        role = request.form.get("role","user")
        pw = request.form.get("password")
        if User.query.filter_by(email=email).first():
            flash("Email already in use","warning")
        else:
            u = User(name=name, email=email, role=role, department_id=dept_id)
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            flash("User created","success")
        return redirect(url_for("users"))
    return render_template("users.html",
                           users=User.query.order_by(User.name).all(),
                           departments=Department.query.order_by(Department.name).all())

@app.route("/tasks/new", methods=["GET","POST"])
@login_required
def task_new():
    require_admin()
    if request.method == "POST":
        t = Task(
            title=request.form["title"],
            description=request.form.get("description"),
            department_id=int(request.form["department_id"]),
            assignee_id=int(request.form["assignee_id"]),
            assigner_id=current_user.id,
            due_date=datetime.strptime(request.form["due_date"], "%Y-%m-%d") if request.form.get("due_date") else None,
            status="OPEN"
        )
        db.session.add(t)
        db.session.commit()
        flash("Task created & assignee notified (check console).","success")
        # "Notify" by printing to console (replace with SMTP or API as needed)
        print(f"[NOTIFY] To:{t.assignee.email} • New Task: {t.title} • Due:{t.due_date}")
        return redirect(url_for("task_view", task_id=t.id))
    return render_template("task_new.html",
                           users=User.query.order_by(User.name).all(),
                           departments=Department.query.order_by(Department.name).all())

@app.route("/tasks/<int:task_id>")
@login_required
def task_view(task_id):
    task = Task.query.get_or_404(task_id)
    if current_user.role != "admin" and current_user.id not in (task.assignee_id, task.assigner_id) and current_user.department_id != task.department_id:
        abort(403)
    return render_template("task_view.html", task=task)

@app.route("/tasks/<int:task_id>/update", methods=["POST"])
@login_required
def task_update(task_id):
    task = Task.query.get_or_404(task_id)
    if current_user.role != "admin" and current_user.id not in (task.assignee_id, task.assigner_id):
        abort(403)

    status = request.form.get("status","COMMENT")
    comment = request.form.get("comment")

    attachment_path = None
    file = request.files.get("attachment")
    if file and file.filename:
        filename = secure_filename(file.filename)
        if not allowed_file(filename):
            flash("File type not allowed","danger")
            return redirect(url_for("task_view", task_id=task.id))
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}")
        file.save(save_path)
        attachment_path = os.path.basename(save_path)

    tu = TaskUpdate(task_id=task.id, user_id=current_user.id, status=status, comment=comment, attachment_path=attachment_path)
    db.session.add(tu)

    # Update task status if completion/rejection
    if status == "COMPLETED":
        task.status = "COMPLETED"
    elif status == "REJECTED":
        task.status = "REJECTED"
    elif status == "PROOF":
        task.status = "IN_PROGRESS"

    db.session.commit()
    flash("Update posted","success")
    return redirect(url_for("task_view", task_id=task.id))

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

# ---- Filters for dashboard ----
@app.route("/filter")
@login_required
def filter_tasks():
    status = request.args.get("status")
    dept = request.args.get("dept", type=int)
    q = Task.query
    if status and status != "ALL":
        q = q.filter_by(status=status)
    if dept:
        q = q.filter_by(department_id=dept)
    tasks = q.order_by(Task.created_at.desc()).all()
    return render_template("dashboard.html", tasks=tasks, selected_status=status or "ALL", selected_dept=dept or 0)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
