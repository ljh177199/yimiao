from config import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    real_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(10), nullable=True)
    id_card = db.Column(db.String(18), nullable=True, unique=True)
    address = db.Column(db.String(200), nullable=True)
    has_allergy = db.Column(db.Boolean, nullable=True)
    contraindications = db.Column(db.Text, nullable=True)
    # 0 = 超级管理员 root；正整数 1,2,3… = 普通用户序号（非布尔）
    is_admin = db.Column(db.Integer, nullable=False, default=1)
    appointments = db.relationship('Appointment', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Vaccine(db.Model):
    __tablename__ = 'vaccines'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    manufacturer = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    stock = db.Column(db.Integer, default=0)
    price = db.Column(db.Float, default=0.0)
    storage_date = db.Column(db.Date, nullable=True)  # 入库时间
    save_time = db.Column(db.Integer, nullable=True)  # 保存时间（天）
    appointments = db.relationship('Appointment', backref='vaccine', lazy=True)

class Appointment(db.Model):
    __tablename__ = 'appointments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vaccine_id = db.Column(db.Integer, db.ForeignKey('vaccines.id'), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    last_vaccination_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='pending')
    rejection_reason = db.Column(db.Text, nullable=True)
    create_time = db.Column(db.DateTime, server_default=db.func.now())
    approve_time = db.Column(db.DateTime, nullable=True)
    vaccination_status = db.Column(db.String(20), default='未接种')  # 接种状态：已接种/未接种
    is_deleted_by_admin = db.Column(db.Boolean, default=False, nullable=False)  # 管理端软删除标记

class AIConversation(db.Model):
    __tablename__ = 'ai_conversations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    create_time = db.Column(db.DateTime, server_default=db.func.now())

class Announcement(db.Model):
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    create_time = db.Column(db.DateTime, server_default=db.func.now())
    update_time = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
