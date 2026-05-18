import pymysql
pymysql.install_as_MySQLdb()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:123456@localhost/vaccine_management'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 数据库连接池配置，优化长时间不操作时的连接稳定性
app.config['SQLALCHEMY_POOL_SIZE'] = 10  # 连接池大小
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 30  # 连接超时时间（秒）
app.config['SQLALCHEMY_POOL_RECYCLE'] = 3600  # 连接回收时间（秒），设置为1小时，确保小于MySQL默认的8小时wait_timeout
app.config['SQLALCHEMY_POOL_PRE_PING'] = True  # 每次获取连接前检测连接是否有效
app.config['SQLALCHEMY_MAX_OVERFLOW'] = 20  # 连接池溢出大小
app.config['SQLALCHEMY_ECHO'] = False  # 关闭SQL语句日志，提高性能
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,  # 与SQLALCHEMY_POOL_PRE_PING功能相同，确保连接有效
    'pool_recycle': 3600,   # 再次确保连接回收时间
    'pool_use_lifo': True,  # 使用LIFO策略，提高连接复用率
    'pool_size': 10,
    'max_overflow': 20,
    'connect_args': {
        'connect_timeout': 30,  # 数据库连接超时设置
        'read_timeout': 30,     # 查询读取超时设置
        'write_timeout': 30,    # 写入操作超时设置
        'charset': 'utf8mb4'    # 确保支持完整的UTF-8字符集
        # 移除init_command，避免SQL语法错误
    }
}

DEEPSEEK_API_KEY = 'sk-dfbb8cbac8184630bbd78b3163fb5a80'
DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'

from models import User, Vaccine, Appointment

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
