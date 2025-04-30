from flask import Flask, request, render_template, send_file, jsonify, redirect, session, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
from encode import hide_document_in_audio
from decode import extract_document_from_audio
from utils import allowed_file, convert_to_wav
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import UserMixin
import time
from werkzeug.utils import secure_filename
import shutil

app = Flask(__name__)

# Database Configuration for SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///flaskapp.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "your_secret_key"  # Change this to a secure secret key

# Initialize database and login manager
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Configure upload folders
UPLOAD_FOLDER = "uploads"
ENCRYPTED_FOLDER = os.path.join(UPLOAD_FOLDER, "encrypted")
DECRYPTED_FOLDER = os.path.join(UPLOAD_FOLDER, "decrypted")

# Create folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ENCRYPTED_FOLDER, exist_ok=True)
os.makedirs(DECRYPTED_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["ENCRYPTED_FOLDER"] = ENCRYPTED_FOLDER
app.config["DECRYPTED_FOLDER"] = DECRYPTED_FOLDER

# Add this after your User model
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    operation = db.Column(db.String(20), nullable=False)  # 'encode' or 'decode'
    file_type = db.Column(db.String(10), nullable=False)
    file_size = db.Column(db.String(20), nullable=False)
    duration = db.Column(db.Float, nullable=False)  # in seconds
    status = db.Column(db.String(20), nullable=False)  # 'success' or 'failed'
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    input_filename = db.Column(db.String(100))
    output_filename = db.Column(db.String(100))
    histogram_filename = db.Column(db.String(100))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/admin")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash("Access denied: Admin privileges required", "danger")
        return redirect(url_for("index"))
    
    users = User.query.all()
    return render_template("admin.html", users=users)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash("Access denied: Admin privileges required", "danger")
        return redirect(url_for("index"))
    
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash("Cannot delete your own account", "danger")
        return redirect(url_for("admin_dashboard"))
    
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/users/<int:user_id>/toggle_admin", methods=["POST"])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash("Access denied: Admin privileges required", "danger")
        return redirect(url_for("index"))
    
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash("Cannot modify your own admin status", "danger")
        return redirect(url_for("admin_dashboard"))
    
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"Admin status {'granted' if user.is_admin else 'revoked'} for {user.username}", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@login_required
def approve_user(user_id):
    if not current_user.is_admin:
        flash("Access denied: Admin privileges required", "danger")
        return redirect(url_for("index"))

    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f"User {user.username} approved successfully!", "success")
    return redirect(url_for("admin_dashboard"))


# Authentication Routes (unchanged)
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            flash("Username already exists!", "danger")
            return redirect(url_for("register"))

        new_user = User(username=username)
        new_user.set_password(password)
        new_user.is_approved = False
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_approved:
                flash("Account pending approval. Please wait for admin to approve your account.", "warning")
                return redirect(url_for("login"))
            
            login_user(user)
            flash("Login successful!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password!", "danger")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully!", "success")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template("home.html")

@app.route("/dashboard")
@login_required
def dashboard():
    # Get today's operation count
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    
    todays_ops = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.timestamp >= today
    ).count()
    
    # Get success rates
    total_ops = Transaction.query.filter_by(user_id=current_user.id).count()
    success_ops = Transaction.query.filter_by(
        user_id=current_user.id, 
        status='success'
    ).count()
    success_rate = f"{(success_ops/total_ops)*100:.1f}%" if total_ops > 0 else "N/A"
    
    return render_template(
        "dashboard.html",
        username=current_user.username,
        todays_ops=todays_ops,
        success_rate=success_rate
    )

@app.route("/encode")
@login_required
def encode_page():
    return render_template("encode.html")

@app.route("/decode")
@login_required
def decode_page():
    return render_template("decode.html")

@app.route("/download/<folder>/<filename>")
@login_required
def download_file(folder, filename):
    if folder == "encrypted":
        path = os.path.join(app.config["ENCRYPTED_FOLDER"], filename)
    elif folder == "decrypted":
        path = os.path.join(app.config["DECRYPTED_FOLDER"], filename)
    else:
        return "Invalid folder", 404
    
     # Normally you would check if the file belongs to the user
    # But admins bypass this check
    if not current_user.is_admin:
        # Here you would validate ownership
        pass  # Add validation if needed
    # For audio playback, don't force download
    if request.args.get('play') == 'true':
        return send_file(path)
    # For download button, force download
    return send_file(path, as_attachment=True)

@app.route('/history/<int:transaction_id>')
@login_required
def view_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    user = User.query.get(transaction.user_id)

    # Only admin or the owner can view it
    if not current_user.is_admin and transaction.user_id != current_user.id:
        flash("Access denied", "danger")
        return redirect(url_for('history'))

    return render_template('transaction_detail.html', transaction=transaction, username=user.username if user else "Unknown")


@app.route('/history')
@login_required
def history():
    # if not current_user.is_admin:
    #     flash("Access denied: Admin privileges required", "danger")
    #     return redirect(url_for("index"))
    # Get transactions for current user, newest first
    if current_user.is_admin:
        transactions_query = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    else:
        transactions_query = Transaction.query.filter_by(user_id=current_user.id)\
            .order_by(Transaction.timestamp.desc()).all()
    
    # Format transactions for template
    transactions = []
    for t in transactions_query:
        user = User.query.get(t.user_id)
        transactions.append({
            'id': t.id,  # <-- ADD THIS
            'timestamp': t.timestamp.strftime('%Y-%m-%d %H:%M'),
            'operation': t.operation,
            'file_type': t.file_type,
            'file_size': t.file_size,
            'duration': f"{t.duration:.2f}",
            'status': t.status,
            'input_filename': t.input_filename,
            'output_filename': t.output_filename,
            'histogram_filename': t.histogram_filename,
            'username': user.username if user else 'Unknown'
        })
    
    total_encodes = Transaction.query.filter_by(operation='encode', status='success').count() if current_user.is_admin else \
                    Transaction.query.filter_by(user_id=current_user.id, operation='encode', status='success').count()
    total_decodes = Transaction.query.filter_by(operation='decode', status='success').count() if current_user.is_admin else \
                    Transaction.query.filter_by(user_id=current_user.id, operation='decode', status='success').count()

    storage_used = 0  # You can update this later to calculate based on real file sizes.
    
    return render_template(
        'history.html',
        transactions=transactions,
        total_encodes=total_encodes,
        total_decodes=total_decodes,
        storage_used=f"{storage_used/1024/1024:.2f} MB",
        admin_view=current_user.is_admin
    )

@app.route('/admin/impersonate/<int:user_id>', methods=["POST"])
@login_required
def impersonate_user(user_id):
    if not current_user.is_admin:
        flash("Access denied: Admin privileges required", "danger")
        return redirect(url_for("index"))
    
    # Save current admin ID
    session["original_admin_id"] = current_user.id
    
    user = User.query.get_or_404(user_id)
    login_user(user)
    flash(f"Now impersonating {user.username}", "info")
    return redirect(url_for("index"))

@app.route('/admin/return')
@login_required
def return_to_admin():
    original_admin_id = session.get("original_admin_id")
    if not original_admin_id:
        flash("No admin session found", "danger")
        return redirect(url_for("index"))
    
    admin_user = User.query.get(original_admin_id)
    if not admin_user or not admin_user.is_admin:
        flash("Original admin account invalid", "danger")
        return redirect(url_for("index"))
    
    login_user(admin_user)
    session.pop("original_admin_id", None)
    flash("Returned to admin account", "success")
    return redirect(url_for("admin_dashboard"))

# Encoding API
# Modify the encode endpoint
@app.route("/encode", methods=["POST"])
@login_required
def encode():
    """Encodes a document inside an audio file."""
    start_time = time.time()
    try:
        if "audio" not in request.files or "document" not in request.files:
            return jsonify({"error": "Missing files"}), 400

        audio = request.files["audio"]
        document = request.files["document"]

        if not allowed_file(audio.filename, {"wav", "mp3", "webm"}):
            return jsonify({"error": "Invalid audio file type"}), 400

        if not allowed_file(document.filename, {"docx", "xlsx", "pdf", "pptx"}):
            return jsonify({"error": "Invalid document file type"}), 400

        # Create unique filenames
        timestamp = str(int(time.time()))
        audio_path = os.path.join(app.config["UPLOAD_FOLDER"], f"audio_{timestamp}_{secure_filename(audio.filename)}")
        doc_path = os.path.join(app.config["UPLOAD_FOLDER"], f"doc_{timestamp}_{secure_filename(document.filename)}")
        encoded_audio_path = os.path.join(app.config["ENCRYPTED_FOLDER"], f"encoded_audio_{timestamp}.wav")

        audio.save(audio_path)
        document.save(doc_path)

        # Get file size
        doc_size = os.path.getsize(doc_path)
        readable_size = f"{doc_size/1024/1024:.2f} MB" if doc_size > 1024*1024 else f"{doc_size/1024:.2f} KB"

        # Convert to WAV if necessary
        audio_path = convert_to_wav(audio_path)

        result = hide_document_in_audio(audio_path, doc_path, encoded_audio_path)
        if "error" in result:
            # Record failed transaction
            new_transaction = Transaction(
                user_id=current_user.id,
                operation="encode",
                file_type=os.path.splitext(document.filename)[1],
                file_size=readable_size,
                duration=time.time() - start_time,
                status="failed",
                input_filename=document.filename,
                output_filename=None
            )
            db.session.add(new_transaction)
            db.session.commit()
            return jsonify({"error": result["error"]}), 400

        # Move histogram to static folder
        static_dir = os.path.join(app.root_path, 'static')
        os.makedirs(static_dir, exist_ok=True)
        histogram_filename = f"histogram_{timestamp}.png"
        static_histogram_path = os.path.join(static_dir, histogram_filename)
        
        try:
            if os.path.exists(result["histogram_path"]):
                if os.path.exists(static_histogram_path):
                    os.remove(static_histogram_path)
                shutil.move(result["histogram_path"], static_histogram_path)
        except Exception as e:
            return jsonify({"error": f"Failed to save histogram: {str(e)}"}), 500

        # Record successful transaction
        new_transaction = Transaction(
            user_id=current_user.id,
            operation="encode",
            file_type=os.path.splitext(document.filename)[1],
            file_size=readable_size,
            duration=time.time() - start_time,
            status="success",
            input_filename=document.filename,
            output_filename=f"encoded_audio_{timestamp}.wav",
            histogram_filename=histogram_filename
        )
        db.session.add(new_transaction)
        db.session.commit()

        # Clean up temporary files
        try:
            os.remove(audio_path)
            os.remove(doc_path)
        except:
            pass

        return jsonify({
            "encoded_audio": f"encoded_audio_{timestamp}.wav",
            "histogram_path": histogram_filename,
            "status": "Encoding successful"
        })

    except Exception as e:
        print("Encoding failed:", str(e))  # Add this to your logs
        return jsonify({"error": f"Encoding failed: {str(e)}"}), 500

# Similarly update the decode endpoint
@app.route("/decode", methods=["POST"])
@login_required
def decode():
    """Decodes a hidden document from an audio file."""
    start_time = time.time()
    if "encoded_audio" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["encoded_audio"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    # Save the uploaded file to encrypted folder first
    timestamp = str(int(time.time()))
    audio_path = os.path.join(app.config["ENCRYPTED_FOLDER"], f"encoded_{timestamp}.wav")
    file.save(audio_path)

    try:
        status, doc_path, histogram_path, elapsed_time = extract_document_from_audio(
            audio_path, 
            app.config["DECRYPTED_FOLDER"]
        )

        if "Error" in status:
            # Record failed transaction
            new_transaction = Transaction(
                user_id=current_user.id,
                operation="decode",
                file_type=".wav",
                file_size=f"{os.path.getsize(audio_path)/1024/1024:.2f} MB",
                duration=time.time() - start_time,
                status="failed",
                input_filename=file.filename,
                output_filename=None
            )
            db.session.add(new_transaction)
            db.session.commit()
            return jsonify({"error": status}), 400

        # Move histogram to static folder
        static_dir = os.path.join(app.root_path, 'static')
        os.makedirs(static_dir, exist_ok=True)
        histogram_filename = os.path.basename(histogram_path)
        static_histogram_path = os.path.join(static_dir, histogram_filename)
        os.rename(histogram_path, static_histogram_path)

        # Get extracted file info
        doc_size = os.path.getsize(doc_path)
        readable_size = f"{doc_size/1024/1024:.2f} MB" if doc_size > 1024*1024 else f"{doc_size/1024:.2f} KB"
        file_ext = os.path.splitext(doc_path)[1]

        # Record successful transaction
        new_transaction = Transaction(
            user_id=current_user.id,
            operation="decode",
            file_type=file_ext,
            file_size=readable_size,
            duration=elapsed_time,
            status="success",
            input_filename=file.filename,
            output_filename=os.path.basename(doc_path),
            histogram_filename=histogram_filename
        )
        db.session.add(new_transaction)
        db.session.commit()

        return jsonify({
            "message": status,
            "document": os.path.basename(doc_path),
            "histogram": histogram_filename,
            "time": elapsed_time
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # Create admin user if it doesn't exist
        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", is_admin=True, is_approved=True)
            admin.set_password("admin123")  # Change this to a secure password
            db.session.add(admin)
            db.session.commit()
    app.run(debug=False, host='0.0.0.0')