import os
import csv
from io import StringIO
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, send_from_directory, abort, Response
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = "my-task-app-secret-key-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to continue."
login_manager.login_message_category = "warning"


# ---------------- MODELS ----------------

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")  # user, admin, superadmin
    is_active_user = db.Column(db.Boolean, default=True)

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
    status = db.Column(db.String(20), default="OPEN")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    task = db.relationship(
        "Task",
        backref=db.backref("updates", order_by="TaskUpdate.created_at.desc()")
    )

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User")

    status = db.Column(db.String(20), default="COMMENT")
    comment = db.Column(db.Text, nullable=True)
    attachment_path = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- UTILITIES ----------------

def require_admin():
    if not current_user.is_authenticated or current_user.role not in ["admin", "superadmin"]:
        abort(403)


def require_superadmin():
    if not current_user.is_authenticated or current_user.role != "superadmin":
        abort(403)


def allowed_file(filename):
    allowed_extensions = {
        "png", "jpg", "jpeg", "pdf", "doc", "docx",
        "xlsx", "ppt", "pptx", "txt", "csv", "zip"
    }
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def get_visible_tasks_query():
    query = Task.query

    if current_user.role == "superadmin":
        return query

    if current_user.role == "admin":
        return query.filter(Task.department_id == current_user.department_id)

    return query.filter(
        (Task.assignee_id == current_user.id) |
        (Task.department_id == current_user.department_id)
    )


def apply_task_filters(query):
    status = request.args.get("status", "ALL")
    department_id = request.args.get("dept", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if status and status != "ALL":
        query = query.filter_by(status=status)

    if department_id:
        query = query.filter_by(department_id=department_id)

    if date_from:
        query = query.filter(Task.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))

    if date_to:
        end_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(Task.created_at < end_date)

    return query, status, department_id, date_from, date_to


# ---------------- AUTH ----------------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for("login"))

    if request.method == "POST":
        dept_name = request.form.get("dept", "Operations").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "danger")
            return redirect(url_for("setup"))

        department = Department(name=dept_name, is_active=True)
        db.session.add(department)

        admin = User(
            name="Admin",
            email=email,
            role="superadmin",
            department=department,
            is_active_user=True
        )
        admin.set_password(password)

        db.session.add(admin)
        db.session.commit()

        flash("Setup complete. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.is_active_user:
                flash("Your account is disabled. Please contact admin.", "danger")
                return redirect(url_for("login"))

            login_user(user)
            return redirect(url_for("index"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department_id = request.form.get("department_id")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "warning")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            role="user",
            department_id=int(department_id) if department_id else None,
            is_active_user=True
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", departments=departments)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------- DASHBOARD ----------------

@app.route("/")
@login_required
def index():
    tasks = get_visible_tasks_query().order_by(Task.created_at.desc()).all()

    if current_user.role == "superadmin":
        departments = Department.query.order_by(Department.name).all()
    else:
        departments = Department.query.filter_by(id=current_user.department_id).all()

    return render_template(
        "dashboard.html",
        tasks=tasks,
        departments=departments,
        selected_status="ALL",
        selected_dept=0,
        date_from="",
        date_to=""
    )


@app.route("/admin")
@login_required
def admin():
    require_admin()
    return redirect(url_for("index"))


@app.route("/filter")
@login_required
def filter_tasks():
    query = get_visible_tasks_query()
    query, status, department_id, date_from, date_to = apply_task_filters(query)

    tasks = query.order_by(Task.created_at.desc()).all()

    if current_user.role == "superadmin":
        departments = Department.query.order_by(Department.name).all()
    else:
        departments = Department.query.filter_by(id=current_user.department_id).all()

    return render_template(
        "dashboard.html",
        tasks=tasks,
        departments=departments,
        selected_status=status,
        selected_dept=department_id or 0,
        date_from=date_from or "",
        date_to=date_to or ""
    )


# ---------------- DEPARTMENTS ----------------

@app.route("/departments", methods=["GET", "POST"])
@login_required
def departments():
    require_superadmin()

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            flash("Department name is required.", "danger")
            return redirect(url_for("departments"))

        if Department.query.filter_by(name=name).first():
            flash("Department already exists.", "warning")
        else:
            db.session.add(Department(name=name, is_active=True))
            db.session.commit()
            flash("Department added successfully.", "success")

        return redirect(url_for("departments"))

    return render_template(
        "departments.html",
        departments=Department.query.order_by(Department.name).all()
    )


@app.route("/departments/<int:dept_id>/edit", methods=["POST"])
@login_required
def edit_department(dept_id):
    require_superadmin()

    department = Department.query.get_or_404(dept_id)
    new_name = request.form.get("name", "").strip()

    if not new_name:
        flash("Department name cannot be empty.", "danger")
        return redirect(url_for("departments"))

    existing = Department.query.filter(
        Department.name == new_name,
        Department.id != dept_id
    ).first()

    if existing:
        flash("Another department with this name already exists.", "warning")
        return redirect(url_for("departments"))

    department.name = new_name
    db.session.commit()

    flash("Department updated successfully.", "success")
    return redirect(url_for("departments"))


@app.route("/departments/<int:dept_id>/toggle", methods=["POST"])
@login_required
def toggle_department(dept_id):
    require_superadmin()

    department = Department.query.get_or_404(dept_id)
    department.is_active = not department.is_active
    db.session.commit()

    flash("Department status updated successfully.", "success")
    return redirect(url_for("departments"))


@app.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
def delete_department(dept_id):
    require_superadmin()

    department = Department.query.get_or_404(dept_id)

    if department.users:
        flash("Cannot delete department because users are assigned to it. Disable it instead.", "danger")
        return redirect(url_for("departments"))

    if department.tasks:
        flash("Cannot delete department because tasks are linked to it. Disable it instead.", "danger")
        return redirect(url_for("departments"))

    db.session.delete(department)
    db.session.commit()

    flash("Department deleted successfully.", "success")
    return redirect(url_for("departments"))


# ---------------- USERS ----------------

@app.route("/users", methods=["GET", "POST"])
@login_required
def users():
    require_admin()

    if current_user.role == "superadmin":
        departments_list = Department.query.order_by(Department.name).all()
    else:
        departments_list = Department.query.filter_by(id=current_user.department_id).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")

        if current_user.role == "superadmin":
            department_id = request.form.get("department_id")
        else:
            department_id = current_user.department_id

        if not name or not email or not password:
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("users"))

        if User.query.filter_by(email=email).first():
            flash("Email already in use.", "warning")
            return redirect(url_for("users"))

        user = User(
            name=name,
            email=email,
            role=role,
            department_id=int(department_id) if department_id else None,
            is_active_user=True
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("User created successfully.", "success")
        return redirect(url_for("users"))

    if current_user.role == "superadmin":
        users_list = User.query.order_by(User.name).all()
    else:
        users_list = User.query.filter_by(
            department_id=current_user.department_id
        ).order_by(User.name).all()

    return render_template(
        "users.html",
        users=users_list,
        departments=departments_list
    )


@app.route("/users/<int:user_id>/edit", methods=["POST"])
@login_required
def edit_user(user_id):
    require_admin()

    user = User.query.get_or_404(user_id)

    if current_user.role != "superadmin" and user.department_id != current_user.department_id:
        abort(403)

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "user")

    if current_user.role == "superadmin":
        department_id = request.form.get("department_id")
    else:
        department_id = current_user.department_id

    if not name or not email:
        flash("Name and email are required.", "danger")
        return redirect(url_for("users"))

    existing = User.query.filter(
        User.email == email,
        User.id != user_id
    ).first()

    if existing:
        flash("Another user with this email already exists.", "warning")
        return redirect(url_for("users"))

    user.name = name
    user.email = email
    user.role = role
    user.department_id = int(department_id) if department_id else None

    db.session.commit()

    flash("User updated successfully.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user(user_id):
    require_admin()

    user = User.query.get_or_404(user_id)

    if current_user.role != "superadmin" and user.department_id != current_user.department_id:
        abort(403)

    if user.id == current_user.id:
        flash("You cannot disable your own account.", "danger")
        return redirect(url_for("users"))

    user.is_active_user = not user.is_active_user
    db.session.commit()

    flash("User status updated successfully.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
def reset_user_password(user_id):
    require_admin()

    user = User.query.get_or_404(user_id)

    if current_user.role != "superadmin" and user.department_id != current_user.department_id:
        abort(403)

    new_password = request.form.get("new_password", "").strip()

    if not new_password:
        flash("Password cannot be empty.", "danger")
        return redirect(url_for("users"))

    user.set_password(new_password)
    db.session.commit()

    flash(f"Password reset successfully for {user.name}.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    require_admin()

    user = User.query.get_or_404(user_id)

    if current_user.role != "superadmin" and user.department_id != current_user.department_id:
        abort(403)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("users"))

    linked_tasks = Task.query.filter(
        (Task.assignee_id == user.id) |
        (Task.assigner_id == user.id)
    ).first()

    if linked_tasks:
        flash("Cannot delete user because tasks are linked to this account. Disable it instead.", "danger")
        return redirect(url_for("users"))

    db.session.delete(user)
    db.session.commit()

    flash("User deleted successfully.", "success")
    return redirect(url_for("users"))


# ---------------- TASKS ----------------

@app.route("/tasks/new", methods=["GET", "POST"])
@login_required
def task_new():
    require_admin()

    if current_user.role == "superadmin":
        active_departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
        active_users = User.query.filter_by(is_active_user=True).order_by(User.name).all()
    else:
        active_departments = Department.query.filter_by(
            id=current_user.department_id,
            is_active=True
        ).all()

        active_users = User.query.filter_by(
            department_id=current_user.department_id,
            is_active_user=True
        ).order_by(User.name).all()

    if request.method == "POST":
        due_date_value = request.form.get("due_date")
        department_id = int(request.form["department_id"])
        assignee_id = int(request.form["assignee_id"])

        if current_user.role != "superadmin" and department_id != current_user.department_id:
            abort(403)

        assignee = User.query.get_or_404(assignee_id)

        if current_user.role != "superadmin" and assignee.department_id != current_user.department_id:
            abort(403)

        department = Department.query.get_or_404(department_id)

        if not department.is_active:
            flash("Cannot create task for a disabled department.", "danger")
            return redirect(url_for("task_new"))

        task = Task(
            title=request.form.get("title", "").strip(),
            description=request.form.get("description", "").strip(),
            department_id=department_id,
            assignee_id=assignee_id,
            assigner_id=current_user.id,
            due_date=datetime.strptime(due_date_value, "%Y-%m-%d").date()
            if due_date_value else None,
            status="OPEN"
        )

        db.session.add(task)
        db.session.commit()

        flash("Task created successfully.", "success")
        return redirect(url_for("task_view", task_id=task.id))

    return render_template(
        "task_new.html",
        users=active_users,
        departments=active_departments
    )


@app.route("/tasks/<int:task_id>")
@login_required
def task_view(task_id):
    task = Task.query.get_or_404(task_id)

    if current_user.role == "superadmin":
        pass
    elif current_user.role == "admin":
        if task.department_id != current_user.department_id:
            abort(403)
    else:
        allowed = (
            current_user.id == task.assignee_id or
            current_user.id == task.assigner_id or
            current_user.department_id == task.department_id
        )
        if not allowed:
            abort(403)

    return render_template("task_view.html", task=task)


@app.route("/tasks/<int:task_id>/update", methods=["POST"])
@login_required
def task_update(task_id):
    task = Task.query.get_or_404(task_id)

    if current_user.role == "superadmin":
        pass
    elif current_user.role == "admin":
        if task.department_id != current_user.department_id:
            abort(403)
    else:
        allowed = (
            current_user.id == task.assignee_id or
            current_user.id == task.assigner_id
        )
        if not allowed:
            abort(403)

    status = request.form.get("status", "COMMENT")
    comment = request.form.get("comment", "").strip()

    attachment_path = None
    file = request.files.get("attachment")

    if file and file.filename:
        filename = secure_filename(file.filename)

        if not allowed_file(filename):
            flash("File type not allowed.", "danger")
            return redirect(url_for("task_view", task_id=task.id))

        saved_filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_filename)

        file.save(save_path)
        attachment_path = saved_filename

    task_update_record = TaskUpdate(
        task_id=task.id,
        user_id=current_user.id,
        status=status,
        comment=comment,
        attachment_path=attachment_path
    )

    db.session.add(task_update_record)

    if status == "COMPLETED":
        task.status = "COMPLETED"
    elif status == "REJECTED":
        task.status = "REJECTED"
    elif status == "PROOF":
        task.status = "IN_PROGRESS"
    elif status == "COMMENT" and task.status == "OPEN":
        task.status = "IN_PROGRESS"

    db.session.commit()

    flash("Update posted successfully.", "success")
    return redirect(url_for("task_view", task_id=task.id))


# ---------------- FILE UPLOADS ----------------

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )


# ---------------- CSV EXPORT ----------------

@app.route("/tasks/export")
@login_required
def export_tasks_csv():
    query = get_visible_tasks_query()
    query, status, department_id, date_from, date_to = apply_task_filters(query)

    tasks = query.order_by(Task.created_at.desc()).all()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Task ID",
        "Title",
        "Description",
        "Department",
        "Assignee",
        "Assignee Email",
        "Assigned By",
        "Due Date",
        "Current Status",
        "Task Created At",
        "Task Updated At",
        "Log Date Time",
        "Log User",
        "Log Status",
        "Log Comment",
        "Attachment"
    ])

    for task in tasks:
        if task.updates:
            for update in task.updates:
                writer.writerow([
                    task.id,
                    task.title,
                    task.description,
                    task.department.name if task.department else "",
                    task.assignee.name if task.assignee else "",
                    task.assignee.email if task.assignee else "",
                    task.assigner.name if task.assigner else "",
                    task.due_date,
                    task.status,
                    task.created_at,
                    task.updated_at,
                    update.created_at,
                    update.user.name if update.user else "",
                    update.status,
                    update.comment,
                    update.attachment_path or ""
                ])
        else:
            writer.writerow([
                task.id,
                task.title,
                task.description,
                task.department.name if task.department else "",
                task.assignee.name if task.assignee else "",
                task.assignee.email if task.assignee else "",
                task.assigner.name if task.assigner else "",
                task.due_date,
                task.status,
                task.created_at,
                task.updated_at,
                "",
                "",
                "",
                "",
                ""
            ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=tasks_report.csv"
    return response


# ---------------- DEBUG DB ----------------

@app.route("/debug/db")
@login_required
def debug_db():
    require_admin()

    return {
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": u.role,
                "active": u.is_active_user,
                "department": u.department.name if u.department else None
            }
            for u in User.query.all()
        ],
        "departments": [
            {
                "id": d.id,
                "name": d.name,
                "active": d.is_active
            }
            for d in Department.query.all()
        ],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "department": t.department.name if t.department else None,
                "assignee": t.assignee.name if t.assignee else None,
                "created_at": str(t.created_at),
                "updated_at": str(t.updated_at)
            }
            for t in Task.query.all()
        ]
    }


# ---------------- RUN APP ----------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)