# 疫苗管理系统

基于 Python + Flask + MySQL 技术栈开发的疫苗管理系统。

## 功能特性

- 用户注册和登录
- 管理员登录（账号：root，密码：123456）
- 疫苗信息展示
- 用户疫苗预约
- 管理员审批预约
- 管理员添加疫苗

## 安装步骤

1. 创建 MySQL 数据库：
```sql
CREATE DATABASE vaccine_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 修改数据库配置：
编辑 `config.py` 文件，修改数据库连接信息：
```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://用户名:密码@localhost/vaccine_management'
```

4. 运行程序：
```bash
python app.py
```

5. 访问系统：
打开浏览器访问：http://127.0.0.1:5000

## 账号信息

- 管理员账号：root
- 管理员密码：123456
- 普通用户需要自行注册

## 使用说明

### 管理员功能
1. 登录管理后台
2. 查看所有预约记录
3. 审批或拒绝预约
4. 添加疫苗信息

### 普通用户功能
1. 注册账号
2. 登录系统
3. 查看疫苗列表
4. 预约疫苗
5. 查看预约状态
