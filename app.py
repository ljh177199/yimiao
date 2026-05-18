from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from config import app, db, DEEPSEEK_API_KEY, DEEPSEEK_API_URL
from models import User, Vaccine, Appointment, AIConversation, Announcement
from datetime import datetime, date, timedelta
import requests
import traceback
from sqlalchemy.exc import OperationalError, DatabaseError
from sqlalchemy import text, inspect
import time
import re

MAX_CHAT_MESSAGE_LENGTH = 500
MAX_CHAT_HISTORY_MESSAGES = 20

ROOT_ADMIN_USERNAME = 'root'


def is_root_system_admin(user):
    """用户名为 root 且 is_admin==0 时为超级管理员，可登录管理端。"""
    return (
        user is not None
        and user.username == ROOT_ADMIN_USERNAME
        and user.is_admin == 0
    )


def is_regular_portal_user(user):
    """is_admin 为正整数时表示普通用户（用户端）。"""
    return user is not None and user.is_admin is not None and user.is_admin > 0


def next_regular_user_is_admin_value():
    """新注册用户：在现有 is_admin 最大值基础上 +1（root 固定为 0，不参与正数竞争）。"""
    mx = db.session.query(db.func.max(User.is_admin)).scalar()
    if mx is None or mx < 1:
        return 1
    return int(mx) + 1


# 数据库连接异常处理装饰器
def handle_db_connection_error(func):
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_interval = 1
        
        for retry in range(max_retries):
            try:
                # 尝试执行原函数
                return func(*args, **kwargs)
            except OperationalError as e:
                # 捕获数据库连接错误
                if retry < max_retries - 1:
                    # 尝试重新连接
                    db.session.rollback()
                    # 关闭旧连接
                    db.engine.dispose()
                    time.sleep(retry_interval)
                    retry_interval *= 2  # 指数退避
                else:
                    # 超过重试次数，返回错误
                    flash('数据库连接错误，请稍后再试', 'error')
                    return redirect(url_for('index'))
            except DatabaseError as e:
                # 其他数据库错误
                db.session.rollback()
                flash(f'数据库错误：{str(e)}', 'error')
                return redirect(url_for('index'))
    return wrapper



@handle_db_connection_error
@app.route('/')
def index():
    return render_template('index.html')

@handle_db_connection_error
@app.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        phone = request.form.get('phone')
        
        # 验证所有字段都已填写
        if not username or not password or not phone:
            flash('请填写用户名、手机号和密码', 'error')
            return render_template('login.html')
        
        # 查询用户（需要同时匹配用户名和手机号）
        user = User.query.filter_by(username=username, phone=phone).first()
        
        if user and user.check_password(password):
            if not is_regular_portal_user(user):
                flash('请使用管理员登录入口', 'error')
                return render_template('login.html')
            login_user(user)
            return redirect(url_for('user_dashboard'))
        else:
            flash('用户名、手机号或密码错误', 'error')
    
    return render_template('login.html')

@handle_db_connection_error
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """管理员登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        phone = request.form.get('phone')
        
        # 验证所有字段都已填写
        if not username or not password or not phone:
            flash('请填写用户名、手机号和密码', 'error')
            return render_template('admin_login.html')
        
        # 查询用户（需要同时匹配用户名和手机号）
        user = User.query.filter_by(username=username, phone=phone).first()
        
        if user and user.check_password(password):
            # 检查是否为超级管理员（is_admin==0）
            if not is_root_system_admin(user):
                flash('您没有管理员权限', 'error')
                return render_template('admin_login.html')
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('用户名、手机号或密码错误', 'error')
    
    return render_template('admin_login.html')

@handle_db_connection_error
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        phone = request.form.get('phone')
        
        # 验证所有字段都已填写
        if not username or not password or not phone:
            flash('请填写所有必填项', 'error')
            return render_template('register.html')
        
        # 验证手机号必须为11位
        if not phone.isdigit() or len(phone) != 11:
            flash('手机号必须为11位数字', 'error')
            return render_template('register.html')
        
        # 验证手机号是否已存在
        if User.query.filter_by(phone=phone).first():
            flash('该手机号已被注册', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
            return render_template('register.html')
        
        if username.strip().lower() == ROOT_ADMIN_USERNAME.lower():
            flash('该用户名不可用', 'error')
            return render_template('register.html')
        
        user = User(
            username=username,
            real_name=username,
            phone=phone,
            is_admin=next_regular_user_is_admin_value(),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return render_template('register.html', redirect_to_login=True)
    
    return render_template('register.html')

@handle_db_connection_error
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        phone = request.form.get('phone')
        
        # 第一步：验证手机号
        if not phone:
            flash('请输入手机号', 'error')
            return render_template('forgot_password.html', step='verify')
        
        # 验证手机号格式
        if not phone.isdigit() or len(phone) != 11:
            flash('手机号必须为11位数字', 'error')
            return render_template('forgot_password.html', step='verify')
        
        # 验证手机号是否存在
        user = User.query.filter_by(phone=phone).first()
        if not user:
            flash('该手机号未注册', 'error')
            return render_template('forgot_password.html', step='verify')
        
        # 第二步：设置新密码和新用户名
        new_username = request.form.get('new_username')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_username and new_password and confirm_password:
            # 验证用户名
            if not new_username:
                flash('请输入新用户名', 'error')
                return render_template('forgot_password.html', step='reset', phone=phone)
            
            # 验证用户名是否已存在
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user.id:
                flash('该用户名已存在', 'error')
                return render_template('forgot_password.html', step='reset', phone=phone)
            
            # 验证密码一致性
            if new_password != confirm_password:
                flash('两次输入的密码不一致', 'error')
                return render_template('forgot_password.html', step='reset', phone=phone)
            
            # 更新用户名和密码
            user.username = new_username
            user.real_name = new_username  # 同时更新真实姓名
            user.set_password(new_password)
            db.session.commit()
            
            flash('密码和用户名重置成功，请登录', 'success')
            return redirect(url_for('login'))
        
        # 手机号验证通过，进入重置密码页面
        return render_template('forgot_password.html', step='reset', phone=phone)
    
    # GET请求，显示验证手机号页面
    return render_template('forgot_password.html', step='verify')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@handle_db_connection_error
@app.route('/user/profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if is_root_system_admin(current_user):
        flash('管理员无法使用用户个人信息功能', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        new_username = (request.form.get('username') or '').strip()
        if not new_username:
            flash('用户名不能为空', 'error')
            return redirect(url_for('edit_profile'))
        if new_username.lower() == ROOT_ADMIN_USERNAME.lower():
            flash('该用户名不可用', 'error')
            return redirect(url_for('edit_profile'))
        taken = User.query.filter(
            User.username == new_username,
            User.id != current_user.id,
        ).first()
        if taken:
            flash('该用户名已被使用', 'error')
            return redirect(url_for('edit_profile'))
        current_user.username = new_username
        # 更新用户信息
        current_user.real_name = request.form.get('real_name')
        current_user.phone = request.form.get('phone')
        current_user.gender = request.form.get('gender')
        current_user.id_card = request.form.get('id_card')
        current_user.address = request.form.get('address')
        current_user.has_allergy = request.form.get('has_allergy') == 'yes'
        current_user.contraindications = request.form.get('contraindications')
        
        try:
            db.session.commit()
            flash('个人信息更新成功', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}', 'error')
        
        return redirect(url_for('edit_profile'))
    
    return render_template('edit_profile.html', user=current_user)

@handle_db_connection_error
@app.route('/user/dashboard')
@login_required
def user_dashboard():
    if is_root_system_admin(current_user):
        return redirect(url_for('admin_dashboard'))
    
    appointments = Appointment.query.filter_by(user_id=current_user.id).order_by(Appointment.create_time.desc()).all()
    # 获取最新的公告（最多5条）
    announcements = Announcement.query.order_by(Announcement.create_time.desc()).limit(5).all()
    return render_template('user_dashboard.html', appointments=appointments, announcements=announcements)

@handle_db_connection_error
@app.route('/vaccines')
@login_required
def vaccine_list():
    vaccines = Vaccine.query.order_by(Vaccine.id.desc()).all()
    current_time = date.today()
    return render_template('vaccine_list.html', vaccines=vaccines, current_time=current_time, timedelta=timedelta)

@handle_db_connection_error
@app.route('/appointment/create/<int:vaccine_id>', methods=['GET', 'POST'])
@login_required
def create_appointment(vaccine_id):
    if is_root_system_admin(current_user):
        flash('管理员不能预约疫苗', 'error')
        return redirect(url_for('vaccine_list'))
    
    vaccine = Vaccine.query.get_or_404(vaccine_id)
    
    if request.method == 'POST':
        appointment_date_str = request.form.get('appointment_date')
        reason = request.form.get('reason')
        last_vaccination_date_str = request.form.get('last_vaccination_date')
        
        try:
            appointment_date = datetime.strptime(appointment_date_str, '%Y-%m-%d').date()
            
            # 解析上一次接种时间（如果有）
            last_vaccination_date = None
            if last_vaccination_date_str:
                last_vaccination_date = datetime.strptime(last_vaccination_date_str, '%Y-%m-%d').date()
            
            if appointment_date < date.today():
                flash('预约日期不能早于今天', 'error')
                return render_template('create_appointment.html', vaccine=vaccine)
            
            if vaccine.stock <= 0:
                flash('该疫苗库存不足', 'error')
                return redirect(url_for('vaccine_list'))
            
            appointment = Appointment(
                user_id=current_user.id,
                vaccine_id=vaccine_id,
                appointment_date=appointment_date,
                reason=reason,
                last_vaccination_date=last_vaccination_date,
                status='pending',
                vaccination_status='未接种'
            )
            db.session.add(appointment)
            db.session.commit()
            
            flash('预约成功，等待管理员审批', 'success')
            return redirect(url_for('user_dashboard'))
        except ValueError:
            flash('日期格式错误', 'error')
    
    return render_template('create_appointment.html', vaccine=vaccine)

@handle_db_connection_error
@app.route('/admin/dashboard', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'publish_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            
            if not title or not content:
                flash('标题和内容不能为空', 'error')
                return redirect(url_for('admin_dashboard', _anchor='announcement-management'))
            
            announcement = Announcement(title=title, content=content)
            db.session.add(announcement)
            db.session.commit()
            
            flash('公告发布成功', 'success')
            return redirect(url_for('admin_dashboard', _anchor='announcement-management'))
        
        elif action == 'approve' and request.form.getlist('appointment_ids'):
            appointment_ids = request.form.getlist('appointment_ids')
            approved_count = 0
            
            for appointment_id in appointment_ids:
                try:
                    appointment = Appointment.query.get(int(appointment_id))
                    if appointment and appointment.status == 'pending':
                        vaccine = Vaccine.query.get(appointment.vaccine_id)
                        if vaccine and vaccine.stock > 0:
                            appointment.status = 'approved'
                            appointment.approve_time = datetime.now()
                            appointment.vaccination_status = '未接种'
                            vaccine.stock -= 1
                            approved_count += 1
                except Exception as e:
                    flash(f'处理预约 {appointment_id} 时出错：{str(e)}', 'error')
            
            db.session.commit()
            
            if approved_count > 0:
                flash(f'成功通过 {approved_count} 条预约', 'success')
            
            return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))
    
    appointments = Appointment.query.filter_by(is_deleted_by_admin=False).order_by(Appointment.create_time.desc()).all()
    vaccines = Vaccine.query.order_by(Vaccine.id.desc()).all()
    announcements = Announcement.query.order_by(Announcement.create_time.desc()).all()
    current_time = date.today()
    return render_template('admin_dashboard.html', appointments=appointments, vaccines=vaccines, announcements=announcements, current_time=current_time, timedelta=timedelta)

@handle_db_connection_error
@app.route('/admin/appointment/approve/<int:appointment_id>')
@login_required
def approve_appointment(appointment_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    appointment = Appointment.query.get_or_404(appointment_id)
    vaccine = Vaccine.query.get(appointment.vaccine_id)
    
    if vaccine.stock <= 0:
        flash('库存不足，无法审批', 'error')
        return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))
    
    appointment.status = 'approved'
    appointment.approve_time = datetime.now()
    vaccine.stock -= 1
    db.session.commit()
    
    flash('审批通过', 'success')
    return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))

@handle_db_connection_error
@app.route('/admin/appointment/reject/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def reject_appointment(appointment_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if request.method == 'POST':
        rejection_reason = request.form.get('rejection_reason', '').strip()
        
        if not rejection_reason:
            flash('请输入拒绝理由', 'error')
            return render_template('reject_appointment.html', appointment=appointment)
        
        appointment.status = 'rejected'
        appointment.rejection_reason = rejection_reason
        appointment.approve_time = datetime.now()
        db.session.commit()
        
        flash('已拒绝该预约', 'success')
        return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))
    
    # 处理GET请求，显示拒绝理由输入表单
    return render_template('reject_appointment.html', appointment=appointment)
    

@handle_db_connection_error
@app.route('/admin/appointment/delete/<int:appointment_id>')
@login_required
def delete_appointment(appointment_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    appointment = Appointment.query.filter_by(id=appointment_id, is_deleted_by_admin=False).first_or_404()

    # 管理端软删除：仅在管理端隐藏，不影响用户端预约记录
    appointment.is_deleted_by_admin = True
    db.session.commit()
    
    flash('预约记录已删除', 'success')
    return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))

@handle_db_connection_error
@app.route('/admin/appointment/clear/all')
@login_required
def clear_all_appointments():
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    # 管理端软删除：仅隐藏管理端记录，不删除用户预约数据
    Appointment.query.filter_by(is_deleted_by_admin=False).update(
        {Appointment.is_deleted_by_admin: True},
        synchronize_session=False
    )
    db.session.commit()
    
    flash('所有预约记录已清空', 'success')
    return redirect(url_for('admin_dashboard', _anchor='appointment-approval'))

@handle_db_connection_error
@app.route('/appointment/cancel/<int:appointment_id>')
@login_required
def cancel_appointment(appointment_id):
    if is_root_system_admin(current_user):
        flash('管理员不能取消预约', 'error')
        return redirect(url_for('admin_dashboard'))
    
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if appointment.user_id != current_user.id:
        flash('权限不足，只能取消自己的预约', 'error')
        return redirect(url_for('user_dashboard'))
    
    if appointment.status != 'pending':
        flash('只能取消待审批的预约', 'error')
        return redirect(url_for('user_dashboard'))
    
    db.session.delete(appointment)
    db.session.commit()
    
    flash('预约已取消', 'success')
    return redirect(url_for('user_dashboard'))

@handle_db_connection_error
@app.route('/admin/vaccine/add', methods=['GET', 'POST'])
@login_required
def add_vaccine():
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        manufacturer = request.form.get('manufacturer')
        description = request.form.get('description')
        stock = request.form.get('stock')
        price = request.form.get('price')
        storage_date_str = request.form.get('storage_date')
        save_time_str = request.form.get('save_time')
        
        # 验证所有必填字段
        if not name or not manufacturer or not description or not stock or not price or not storage_date_str or not save_time_str:
            flash('所有字段都是必填项，请填写完整信息', 'error')
            return redirect(url_for('add_vaccine'))
        
        # 处理入库时间
        storage_date = None
        if storage_date_str:
            storage_date = datetime.strptime(storage_date_str, '%Y-%m-%d').date()
            # 验证入库时间不能超过当天日期
            if storage_date > date.today():
                flash('入库时间不能超过当天日期', 'error')
                return redirect(url_for('add_vaccine'))
        
        # 处理保存时间
        save_time = None
        if save_time_str:
            save_time = int(save_time_str)
        
        # 检查是否已存在相同名称和厂家的疫苗
        existing_vaccine = Vaccine.query.filter_by(name=name, manufacturer=manufacturer).first()
        if existing_vaccine:
            flash('当前疫苗已存在，无法添加', 'error')
            return redirect(url_for('add_vaccine'))
        
        # 使用递增ID，确保新增疫苗在按ID倒序时显示在首位
        max_id = db.session.query(db.func.max(Vaccine.id)).scalar()
        new_id = (max_id or 0) + 1
        
        vaccine = Vaccine(
            id=new_id,
            name=name,
            manufacturer=manufacturer,
            description=description,
            stock=int(stock),
            price=float(price),
            storage_date=storage_date,
            save_time=save_time
        )
        db.session.add(vaccine)
        db.session.commit()
        
        flash('疫苗添加成功', 'success')
        # 新增成功后回到疫苗管理区域；只有具体疫苗锚点才触发单条高亮
        return redirect(url_for('admin_dashboard', _anchor='vaccine-management'))
    
    return render_template('add_vaccine.html')

@handle_db_connection_error
@app.route('/admin/vaccine/delete/<int:vaccine_id>')
@login_required
def delete_vaccine(vaccine_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    vaccine = Vaccine.query.get_or_404(vaccine_id)
    
    pending_appointments = Appointment.query.filter_by(vaccine_id=vaccine_id, status='pending').all()
    if pending_appointments:
        flash('该疫苗有待审批的预约，无法删除', 'error')
        return redirect(url_for('admin_dashboard', _anchor=f'vaccine-{vaccine_id}'))
    
    all_appointments = Appointment.query.filter_by(vaccine_id=vaccine_id).all()
    for appointment in all_appointments:
        db.session.delete(appointment)
    
    # 查找下一个相邻的疫苗ID（用于删除后定位）
    next_vaccine = Vaccine.query.filter(Vaccine.id > vaccine_id).order_by(Vaccine.id.asc()).first()
    prev_vaccine = Vaccine.query.filter(Vaccine.id < vaccine_id).order_by(Vaccine.id.desc()).first()
    
    db.session.delete(vaccine)
    db.session.commit()
    
    flash('疫苗删除成功', 'success')
    
    # 优先跳转到下一个疫苗，如果没有则跳转到上一个，都没有则跳转到疫苗管理区域
    if next_vaccine:
        return redirect(url_for('admin_dashboard', _anchor=f'vaccine-{next_vaccine.id}'))
    elif prev_vaccine:
        return redirect(url_for('admin_dashboard', _anchor=f'vaccine-{prev_vaccine.id}'))
    else:
        return redirect(url_for('admin_dashboard', _anchor='vaccine-management'))

@handle_db_connection_error
@app.route('/admin/vaccine/edit/<int:vaccine_id>', methods=['GET', 'POST'])
@login_required
def edit_vaccine(vaccine_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    vaccine = Vaccine.query.get_or_404(vaccine_id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            manufacturer = request.form.get('manufacturer')
            description = request.form.get('description')
            stock = request.form.get('stock')
            price = request.form.get('price')
            storage_date_str = request.form.get('storage_date')
            save_time_str = request.form.get('save_time')
            
            # 处理入库时间
            storage_date = None
            if storage_date_str:
                storage_date = datetime.strptime(storage_date_str, '%Y-%m-%d').date()
                # 验证入库时间不能超过当天日期
                if storage_date > date.today():
                    flash('入库时间不能超过当天日期', 'error')
                    return redirect(url_for('edit_vaccine', vaccine_id=vaccine_id))
            
            # 处理保存时间
            save_time = None
            if save_time_str:
                save_time = int(save_time_str)
            
            # 更新疫苗信息
            vaccine.name = name
            vaccine.manufacturer = manufacturer
            vaccine.description = description
            vaccine.stock = int(stock)
            vaccine.price = float(price)
            vaccine.storage_date = storage_date
            vaccine.save_time = save_time
            
            db.session.commit()
            
            flash('疫苗信息更新成功', 'success')
            return redirect(url_for('admin_dashboard', _anchor=f'vaccine-{vaccine_id}'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}', 'error')
            return redirect(url_for('edit_vaccine', vaccine_id=vaccine_id))
    
    return render_template('edit_vaccine.html', vaccine=vaccine)

@app.route('/ai_chat')
@login_required
def ai_chat():
    return render_template('ai_chat.html')

@app.route('/api/ai_chat', methods=['POST'])
@login_required
def ai_chat_api():
    payload = request.get_json(silent=True) or {}
    user_message = payload.get('message', '').strip()
    conversation_history = payload.get('conversation_history', [])
    
    if not user_message:
        return jsonify({'error': '请输入消息'}), 400

    if len(user_message) > MAX_CHAT_MESSAGE_LENGTH:
        return jsonify({'error': f'消息过长，请控制在{MAX_CHAT_MESSAGE_LENGTH}字以内'}), 400

    if not isinstance(conversation_history, list):
        conversation_history = []
    
    try:
        user_message_lower = user_message.lower()

        # 定义查询意图关键词
        query_patterns = {
            'my_appointments': ['我的预约', '预约记录', '我的订单', '预约状态', '我预约', '查询预约'],
            'vaccine_list': ['疫苗列表', '有什么疫苗', '疫苗种类', '系统疫苗', '库存疫苗', '可预约疫苗'],
            'vaccine_stock': ['疫苗库存', '库存多少', '还剩多少', '还有货吗', '库存情况'],
            'system_stats': ['系统统计', '系统数据', '有多少用户', '总预约数', '系统概况']
        }

        # 隐私保护：拦截个人敏感信息查询
        privacy_keywords = [
            '个人信息', '我的信息', '我的资料', '我是谁', '我叫什么',
            '姓名', '手机号', '电话', '身份证', '住址', '地址', '过敏史'
        ]
        if any(keyword in user_message_lower for keyword in privacy_keywords):
            response_text = (
                "为保护隐私安全，AI助手不提供任何个人敏感信息查询服务。"
                "\n\n您可以咨询：\n1. 疫苗知识\n2. 疫苗库存与种类\n3. 预约流程与接种建议"
            )

            user_conversation = AIConversation(
                user_id=current_user.id,
                role='user',
                content=user_message
            )
            db.session.add(user_conversation)

            ai_conversation = AIConversation(
                user_id=current_user.id,
                role='assistant',
                content=response_text
            )
            db.session.add(ai_conversation)
            db.session.commit()

            return jsonify({'response': response_text})
        
        # 检测用户查询意图
        detected_intent = None
        
        for intent, keywords in query_patterns.items():
            for keyword in keywords:
                if keyword in user_message_lower:
                    detected_intent = intent
                    break
            if detected_intent:
                break
        
        # 上下文关联分析：检查是否是追问或相关问题
        context_info = analyze_conversation_context(conversation_history, user_message)
        matched_vaccine = None
        
        if context_info.get('context_vaccine'):
            # 如果检测到上下文关联的疫苗，优先使用上下文中的疫苗
            matched_vaccine = context_info['context_vaccine']
        
        # 检查是否是特定疫苗查询（包含"有没有"、"是否有"、"库存"等关键词）
        specific_vaccine_keywords = ['有没有', '是否有', '库存', '还有', '剩余', '查一下', '查询']
        is_specific_query = any(kw in user_message_lower for kw in specific_vaccine_keywords)
        
        if is_specific_query and not detected_intent and not matched_vaccine:
            # 定义疫苗别名映射（常见简称到标准名称的映射）
            vaccine_aliases = {
                '乙肝': ['乙型肝炎', '乙肝'],
                '甲肝': ['甲型肝炎', '甲肝'],
                '丙肝': ['丙型肝炎', '丙肝'],
                '流感': ['流感'],
                '新冠': ['新冠', 'COVID', '冠状病毒'],
                'HPV': ['HPV', '人乳头瘤', '宫颈癌'],
                '水痘': ['水痘'],
                '麻疹': ['麻疹'],
                '百白破': ['百白破', '百日咳', '白喉', '破伤风'],
                '卡介苗': ['卡介苗', '结核'],
                '肺炎': ['肺炎'],
                '轮状': ['轮状'],
                '手足口': ['手足口', 'EV71'],
                '乙脑': ['乙脑', '乙型脑炎'],
                '流脑': ['流脑', '脑膜炎'],
                '麻腮风': ['麻腮风', '麻疹', '腮腺炎', '风疹'],
                '脊灰': ['脊灰', '脊髓灰质炎', '小儿麻痹'],
                '狂犬': ['狂犬'],
                '破伤风': ['破伤风'],
                '伤寒': ['伤寒'],
                '霍乱': ['霍乱'],
                '黄热': ['黄热'],
                '甲肝': ['甲型肝炎', '甲肝'],
                '带状疱疹': ['带状疱疹', '重组带状疱疹']
            }
            
            # 获取所有疫苗名称进行匹配
            all_vaccines = Vaccine.query.all()
            
            for vaccine in all_vaccines:
                # 检查疫苗名称是否在用户消息中（支持部分匹配）
                vaccine_name_lower = vaccine.name.lower()
                # 移除常见词汇后进行匹配
                clean_name = vaccine_name_lower.replace('疫苗', '').replace('(', '').replace(')', '').strip()
                
                # 双向匹配：疫苗名称在用户消息中，或用户消息中的关键词在疫苗名称中
                if (clean_name in user_message_lower or 
                    vaccine_name_lower in user_message_lower):
                    matched_vaccine = vaccine
                    break
                
                # 检查用户消息中的关键词是否匹配疫苗别名
                for alias, keywords in vaccine_aliases.items():
                    if alias in user_message_lower:
                        # 检查疫苗名称是否包含该别名的任何关键词
                        for keyword in keywords:
                            if keyword in vaccine_name_lower:
                                matched_vaccine = vaccine
                                break
                        if matched_vaccine:
                            break
                
                if matched_vaccine:
                    break
                
                # 检查用户消息中的每个词是否在疫苗名称中
                user_words = [w for w in user_message_lower.split() if len(w) >= 2 and w not in ['有没有', '是否有', '库存', '还有', '剩余', '查一下', '查询', '疫苗']]
                for word in user_words:
                    if word in vaccine_name_lower and len(word) >= 2:
                        matched_vaccine = vaccine
                        break
                if matched_vaccine:
                    break
            
            if matched_vaccine:
                response_text = generate_specific_vaccine_response(matched_vaccine)
                
                # 保存对话到数据库
                user_conversation = AIConversation(
                    user_id=current_user.id,
                    role='user',
                    content=user_message
                )
                db.session.add(user_conversation)
                
                ai_conversation = AIConversation(
                    user_id=current_user.id,
                    role='assistant',
                    content=response_text
                )
                db.session.add(ai_conversation)
                db.session.commit()
                
                return jsonify({'response': response_text})
            else:
                # 没有找到匹配的疫苗，返回提示
                response_text = '抱歉，系统中没有找到您查询的疫苗。\n\n您可以：\n1. 使用"疫苗列表"查看所有可用疫苗\n2. 检查疫苗名称是否正确\n3. 使用更简短的疫苗名称查询（如"甲肝"、"乙肝"等）'
                
                # 保存对话到数据库
                user_conversation = AIConversation(
                    user_id=current_user.id,
                    role='user',
                    content=user_message
                )
                db.session.add(user_conversation)
                
                ai_conversation = AIConversation(
                    user_id=current_user.id,
                    role='assistant',
                    content=response_text
                )
                db.session.add(ai_conversation)
                db.session.commit()
                
                return jsonify({'response': response_text})
        
        # 根据意图直接查询数据库并返回结果
        if detected_intent:
            response_text = generate_system_response(detected_intent)
            
            # 保存对话到数据库
            user_conversation = AIConversation(
                user_id=current_user.id,
                role='user',
                content=user_message
            )
            db.session.add(user_conversation)
            
            ai_conversation = AIConversation(
                user_id=current_user.id,
                role='assistant',
                content=response_text
            )
            db.session.add(ai_conversation)
            db.session.commit()
            
            return jsonify({'response': response_text})
        
        # 如果不是系统查询，使用AI回答
        # 获取系统数据用于AI上下文
        system_context = get_system_context()
        
        headers = {
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # 构建消息列表，包含对话历史上下文
        messages = [
            {
                'role': 'system',
                'content': f'你是疫苗管理系统的AI助手。当用户询问系统相关信息（如预约记录、疫苗库存）时，请直接回答。当用户询问疫苗专业知识时，基于你的知识回答。\n\n隐私安全要求（必须遵守）：\n- 严禁提供任何个人敏感信息（姓名、电话、身份证、住址、过敏史等）。\n- 遇到个人信息相关问题，统一回复：为保护隐私安全，AI助手不提供个人信息查询服务。\n\n请尽量使用以下结构回复，提高可读性：\n1. 核心结论（1-2句）\n2. 详细说明（分点列出）\n3. 接下来建议（1-3条可执行建议）\n\n当前系统数据：\n{system_context}\n\n注意：\n- 绝对不要编造任何数据。\n- 回答尽量简洁、准确、可执行。\n- 请保持对话连贯性，理解用户追问和上下文关联问题。'
            }
        ]
        
        # 添加对话历史（最多最近5轮对话）
        if conversation_history:
            # 过滤掉系统消息，只保留用户和助手的对话
            valid_history = [
                msg for msg in conversation_history
                if isinstance(msg, dict)
                and msg.get('role') in ['user', 'assistant']
                and isinstance(msg.get('content'), str)
            ]
            # 只保留最近10轮（20条消息）
            recent_history = valid_history[-MAX_CHAT_HISTORY_MESSAGES:]
            messages.extend(recent_history)
        
        # 添加当前用户消息
        messages.append({
            'role': 'user',
            'content': user_message
        })
        
        data = {
            'model': 'deepseek-chat',
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': 1000
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        ai_response = result['choices'][0]['message']['content']
        
        # 去掉回答中的星号，避免展示 markdown 强调符
        filtered_response = ai_response.replace('*', '').strip()
        
        # 保存用户消息到数据库
        user_conversation = AIConversation(
            user_id=current_user.id,
            role='user',
            content=user_message
        )
        db.session.add(user_conversation)
        
        # 保存AI回复到数据库
        ai_conversation = AIConversation(
            user_id=current_user.id,
            role='assistant',
            content=filtered_response
        )
        db.session.add(ai_conversation)
        db.session.commit()
        
        return jsonify({'response': filtered_response})
    
    except requests.exceptions.Timeout:
        return jsonify({'error': 'AI响应超时，请稍后重试或换个更简短的问题'}), 504
    except requests.exceptions.RequestException:
        return jsonify({'error': 'AI服务暂时不可用，请稍后重试'}), 502
    except KeyError as e:
        return jsonify({'error': f'响应格式错误：{str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'服务器错误：{str(e)}'}), 500


def generate_system_response(intent):
    """基于数据库查询生成系统响应"""
    
    if intent == 'my_appointments':
        # 查询当前用户的预约记录
        appointments = Appointment.query.filter_by(user_id=current_user.id).order_by(Appointment.create_time.desc()).all()
        
        if not appointments:
            return "根据系统记录，您目前没有预约记录。\n\n您可以：\n1. 前往疫苗列表页面查看可预约的疫苗\n2. 选择心仪的疫苗进行预约"
        
        response = "根据系统数据库，您的预约记录如下：\n\n"
        for i, appointment in enumerate(appointments, 1):
            vaccine_name = appointment.vaccine.name if appointment.vaccine else '未知疫苗'
            manufacturer = appointment.vaccine.manufacturer if appointment.vaccine else '未知厂家'
            status_map = {
                'pending': '待审批',
                'approved': '已通过',
                'rejected': '已拒绝'
            }
            status = status_map.get(appointment.status, appointment.status)
            
            response += f"{i}. {vaccine_name}\n"
            response += f"   厂家：{manufacturer}\n"
            response += f"   预约日期：{appointment.appointment_date.strftime('%Y-%m-%d')}\n"
            response += f"   状态：{status}\n"
            response += f"   创建时间：{appointment.create_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            if appointment.rejection_reason:
                response += f"   拒绝原因：{appointment.rejection_reason}\n"
            response += "\n"
        
        return response
    
    elif intent == 'vaccine_list':
        # 查询所有疫苗
        vaccines = Vaccine.query.all()
        
        if not vaccines:
            return "系统中暂时没有疫苗信息。"
        
        response = f"系统共有 {len(vaccines)} 种疫苗：\n\n"
        for i, vaccine in enumerate(vaccines, 1):
            response += f"{i}. {vaccine.name}\n"
            response += f"   厂家：{vaccine.manufacturer}\n"
            response += f"   库存：{vaccine.stock}支\n"
            response += f"   价格：{vaccine.price}元\n"
            if vaccine.description:
                response += f"   说明：{vaccine.description}\n"
            response += "\n"
        
        return response
    
    elif intent == 'vaccine_stock':
        # 查询疫苗库存
        vaccines = Vaccine.query.all()
        
        if not vaccines:
            return "系统中暂时没有疫苗信息。"
        
        total_stock = sum(v.stock for v in vaccines)
        low_stock_vaccines = [v for v in vaccines if v.stock < 10]
        
        response = f"系统疫苗库存统计：\n\n"
        response += f"1. 疫苗种类：{len(vaccines)}种\n"
        response += f"2. 总库存：{total_stock}支\n\n"
        
        response += "各疫苗库存详情：\n"
        for i, vaccine in enumerate(vaccines, 1):
            stock_status = "库存充足" if vaccine.stock >= 10 else "库存紧张"
            response += f"{i}. {vaccine.name} - {vaccine.stock}支（{stock_status}）\n"
        
        if low_stock_vaccines:
            response += "\n库存预警（库存少于10支）：\n"
            for vaccine in low_stock_vaccines:
                response += f"- {vaccine.name}：仅剩{vaccine.stock}支\n"
        
        return response
    
    elif intent == 'system_stats':
        # 查询系统统计
        total_users = User.query.count()
        total_appointments = Appointment.query.count()
        total_vaccines = Vaccine.query.count()
        total_stock = sum(v.stock for v in Vaccine.query.all())
        
        pending_count = Appointment.query.filter_by(status='pending').count()
        approved_count = Appointment.query.filter_by(status='approved').count()
        rejected_count = Appointment.query.filter_by(status='rejected').count()
        
        response = "系统数据统计：\n\n"
        response += f"1. 注册用户总数：{total_users}人\n"
        response += f"2. 疫苗种类：{total_vaccines}种\n"
        response += f"3. 疫苗总库存：{total_stock}支\n"
        response += f"4. 总预约数：{total_appointments}条\n"
        response += f"   - 待审批：{pending_count}条\n"
        response += f"   - 已通过：{approved_count}条\n"
        response += f"   - 已拒绝：{rejected_count}条\n"
        
        return response
    
    return "抱歉，我无法理解您的查询请求。"


def generate_specific_vaccine_response(vaccine):
    """生成特定疫苗的查询响应"""
    response = f"根据系统数据库查询结果：\n\n"
    response += f"疫苗名称：{vaccine.name}\n"
    response += f"生产厂家：{vaccine.manufacturer}\n"
    response += f"当前库存：{vaccine.stock}支\n"
    response += f"价格：{vaccine.price}元\n"
    
    # 库存状态判断
    if vaccine.stock <= 0:
        response += "库存状态：暂时缺货，无法预约\n"
    elif vaccine.stock < 10:
        response += "库存状态：库存紧张，建议尽快预约\n"
    else:
        response += "库存状态：库存充足，可以预约\n"
    
    if vaccine.description:
        response += f"\n疫苗说明：{vaccine.description}\n"
    
    if vaccine.storage_date:
        response += f"入库时间：{vaccine.storage_date.strftime('%Y-%m-%d')}\n"
    
    if vaccine.save_time:
        response += f"保存期限：{vaccine.save_time}天\n"
    
    # 添加预约建议
    if vaccine.stock > 0:
        response += "\n您可以通过以下方式预约：\n"
        response += "1. 前往疫苗列表页面\n"
        response += "2. 点击该疫苗的预约按钮\n"
        response += "3. 填写预约信息并提交\n"
    else:
        response += "\n该疫苗暂时缺货，您可以：\n"
        response += "1. 查看其他可预约的疫苗\n"
        response += "2. 稍后再次查询库存情况\n"
    
    return response


def analyze_conversation_context(conversation_history, current_message):
    """分析对话上下文，识别关联问题和追问"""
    context_info = {
        'context_vaccine': None,
        'last_topic': None,
        'is_follow_up': False
    }
    
    if not conversation_history or len(conversation_history) < 2:
        return context_info
    
    # 获取最近的几轮对话（最多最近3轮）
    recent_history = conversation_history[-6:]  # 3轮对话 = 6条消息
    
    # 从对话历史中提取提到的疫苗
    mentioned_vaccines = []
    all_vaccines = Vaccine.query.all()
    
    for msg in recent_history:
        if msg.get('role') == 'assistant':
            content = msg.get('content', '')
            # 检查AI回复中提到的疫苗
            for vaccine in all_vaccines:
                if vaccine.name in content or vaccine.manufacturer in content:
                    mentioned_vaccines.append(vaccine)
    
    # 去重，保留最近提到的疫苗
    seen_ids = set()
    unique_vaccines = []
    for v in reversed(mentioned_vaccines):  # 从后往前，保留最近提到的
        if v.id not in seen_ids:
            seen_ids.add(v.id)
            unique_vaccines.insert(0, v)
    
    # 分析当前消息是否是追问
    follow_up_keywords = ['它', '这个', '那个', '刚才', '上面', '之前', '说的', '这款', '这种', '这个疫苗']
    is_follow_up = any(kw in current_message for kw in follow_up_keywords)
    
    # 检查是否是简短的问题（可能是追问）
    is_short_question = len(current_message) < 15 and ('呢' in current_message or '吗' in current_message or '？' in current_message)
    
    # 如果检测到追问且历史中有提到的疫苗
    if (is_follow_up or is_short_question) and unique_vaccines:
        context_info['context_vaccine'] = unique_vaccines[-1]  # 使用最近提到的疫苗
        context_info['last_topic'] = 'vaccine'
        context_info['is_follow_up'] = True
    
    return context_info


def get_system_context():
    """获取系统上下文信息用于AI"""
    # 获取疫苗数量
    vaccine_count = Vaccine.query.count()
    
    # 获取预约数量
    appointment_count = Appointment.query.filter_by(user_id=current_user.id).count()
    
    return f"当前为登录用户会话，系统疫苗种类：{vaccine_count}种，当前用户预约记录：{appointment_count}条"

@app.route('/api/ai_chat/history', methods=['GET'])
@login_required
def get_ai_chat_history():
    try:
        conversations = AIConversation.query.filter_by(user_id=current_user.id).order_by(AIConversation.create_time.asc()).all()
        
        history = []
        for conv in conversations:
            history.append({
                'role': conv.role,
                'content': conv.content
            })
        
        return jsonify({'history': history})
    
    except Exception as e:
        return jsonify({'error': f'获取历史记录失败：{str(e)}'}), 500

@app.route('/api/ai_chat/history/clear', methods=['POST'])
@login_required
def clear_ai_chat_history():
    try:
        AIConversation.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        
        return jsonify({'success': True, 'message': '历史记录已清空'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'清空历史记录失败：{str(e)}'}), 500

@handle_db_connection_error
@app.route('/admin/users')
@login_required
def admin_users():
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    users = User.query.filter(User.is_admin > 0).order_by(User.id).all()
    return render_template('admin_users.html', users=users)

@handle_db_connection_error
@app.route('/admin/user/<int:user_id>')
@login_required
def admin_user_detail(user_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    user = User.query.get_or_404(user_id)
    appointments = Appointment.query.filter_by(user_id=user_id).order_by(Appointment.create_time.desc()).all()
    return render_template('admin_user_detail.html', user=user, appointments=appointments)

@app.route('/admin/appointment/<int:appointment_id>/vaccination-status', methods=['POST'])
@login_required
def update_appointment_vaccination_status(appointment_id):
    if not is_root_system_admin(current_user):
        return jsonify({'success': False, 'message': '权限不足'})
    
    appointment = Appointment.query.get_or_404(appointment_id)
    # 直接从表单中获取数据
    vaccination_status = request.form.get('vaccination_status')
    

    
    # 检查 vaccination_status 是否为 None
    if not vaccination_status:
        return jsonify({'success': False, 'message': '接种状态不能为空'})
    
    if vaccination_status not in ['已接种', '未接种']:
        return jsonify({'success': False, 'message': '无效的接种状态'})
    
    try:
        # 更新接种状态
        appointment.vaccination_status = vaccination_status
        db.session.commit()
        return jsonify({'success': True, 'message': '接种状态更新成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败：{str(e)}'})

@handle_db_connection_error
@app.route('/api/appointment/<int:appointment_id>/vaccination-status', methods=['GET'])
@login_required
def get_appointment_vaccination_status(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # 验证预约是否属于当前用户
    if appointment.user_id != current_user.id:
        return jsonify({'success': False, 'message': '无权限查看该预约'})
    
    return jsonify({
        'success': True,
        'vaccination_status': appointment.vaccination_status or '未接种'
    })

@handle_db_connection_error
@app.route('/admin/announcement/edit/<int:announcement_id>', methods=['GET', 'POST'])
@login_required
def edit_announcement(announcement_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    announcement = Announcement.query.get_or_404(announcement_id)
    
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        
        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return redirect(url_for('edit_announcement', announcement_id=announcement_id))
        
        announcement.title = title
        announcement.content = content
        db.session.commit()
        
        flash('公告更新成功', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_announcement.html', announcement=announcement)

@handle_db_connection_error
@app.route('/admin/announcement/delete/<int:announcement_id>')
@login_required
def delete_announcement(announcement_id):
    if not is_root_system_admin(current_user):
        flash('权限不足', 'error')
        return redirect(url_for('user_dashboard'))
    
    announcement = Announcement.query.get_or_404(announcement_id)
    db.session.delete(announcement)
    db.session.commit()
    
    flash('公告已删除', 'success')
    return redirect(url_for('admin_dashboard'))


def _ensure_users_is_admin_int_column():
    """历史库中 is_admin 可能为布尔型，改为 INT 以存储 0 与正整数序号（MySQL）。"""
    try:
        inspector = inspect(db.engine)
        if 'users' not in inspector.get_table_names():
            return
    except Exception:
        return
    if db.engine.dialect.name != 'mysql':
        return
    try:
        db.session.execute(
            text('ALTER TABLE users MODIFY COLUMN is_admin INT NOT NULL DEFAULT 1')
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def _sync_is_admin_role_codes(root_username):
    """root 的 is_admin 固定为 0；普通用户为正整数。若存在非 root 且 is_admin=0 的旧数据，按 id 顺序重编号为 1..n。"""
    root = User.query.filter_by(username=root_username).first()
    if not root:
        return
    legacy = User.query.filter(
        User.username != root_username,
        User.is_admin == 0,
    ).count()
    if legacy > 0:
        others = User.query.filter(User.username != root_username).order_by(User.id).all()
        for i, u in enumerate(others, start=1):
            u.is_admin = i
    root.is_admin = 0
    db.session.commit()


def init_db():
    with app.app_context():
        db.create_all()
        # 兼容历史数据库：为 appointments 表补充管理端软删除字段（兼容 MySQL/SQLite）
        inspector = inspect(db.engine)
        column_names = {column['name'] for column in inspector.get_columns('appointments')}
        if 'is_deleted_by_admin' not in column_names:
            db.session.execute(
                text("ALTER TABLE appointments ADD COLUMN is_deleted_by_admin BOOLEAN NOT NULL DEFAULT 0")
            )
            db.session.commit()

        _ensure_users_is_admin_int_column()

        default_admin_username = ROOT_ADMIN_USERNAME
        default_admin_password = '123456'
        default_admin_phone = '11111111111'
        default_admin_real_name = '小R'

        admin = User.query.filter_by(username=default_admin_username).first()
        if not admin:
            admin = User(
                username=default_admin_username,
                real_name=default_admin_real_name,
                phone=default_admin_phone,
                is_admin=0,
            )
            admin.set_password(default_admin_password)
            db.session.add(admin)
            db.session.commit()
            print('管理员账号创建成功：root/123456')
        else:
            # root账号已存在时，同步管理员显示名，避免仅修改代码但页面不生效
            if admin.real_name != default_admin_real_name:
                admin.real_name = default_admin_real_name
                db.session.commit()
                print(f'管理员显示名已同步为：{default_admin_real_name}')

        _sync_is_admin_role_codes(default_admin_username)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
