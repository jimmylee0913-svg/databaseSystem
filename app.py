from flask import Flask, jsonify, request
from datetime import datetime, timedelta, timezone 
import json
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy 
from sqlalchemy import text # 導入 text 用於清空操作

# 定義台灣時區 (UTC+8)
TAIWAN_TZ = timezone(timedelta(hours=8))


# --- 初始化 Flask 應用 ---
app = Flask(__name__)
# 啟用 CORS：允許前端 (例如在不同 port 運行) 訪問後端 API
CORS(app) 

# --- 模擬資料庫 ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db' # 數據庫檔案將存為 site.db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 
db = SQLAlchemy(app)

# VVVV 新增 ContactInfo 資料表 VVVV
class ContactInfo(db.Model):
    __tablename__ = 'contact_info'
    id = db.Column(db.Integer, primary_key=True)
    contact_name = db.Column(db.String(100), nullable=False)
    contact_phone = db.Column(db.String(100), nullable=False)
    delivery_address = db.Column(db.String(255), nullable=True)
    pickup_type = db.Column(db.String(50), nullable=False) # 現場取餐 / 外送

    def __repr__(self):
        return f"ContactInfo('{self.contact_name}', '{self.contact_phone}')"
# ^^^^ 新增 ContactInfo 資料表 ^^^^


# VVVV 修改 Order 資料表：使用外鍵關聯 ContactInfo VVVV
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, unique=True, nullable=False) # 您的訂單編號
    status = db.Column(db.String(20), nullable=False, default='pending')
    final_amount = db.Column(db.Float, nullable=False)
    items_json = db.Column(db.Text, nullable=False) 
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(TAIWAN_TZ))
    
    # 外鍵到 ContactInfo
    contact_id = db.Column(db.Integer, db.ForeignKey('contact_info.id'), nullable=False)
    
    # 建立關係屬性，方便從 Order 訪問 ContactInfo 的資料
    contact = db.relationship('ContactInfo', backref='orders', lazy=True)

    def __repr__(self):
        return f"Order('{self.order_id}', '{self.status}', '{self.final_amount}')"
# ^^^^ 修改 Order 資料表 ^^^^


# 菜單資料 (與前端保持一致)
MENU_ITEMS = [
    {"id": 1, "name": "珍珠奶茶", "price": 60, "category": "milk-tea", "isPopular": True},
    {"id": 2, "name": "四季春青茶", "price": 40, "category": "fruit-tea", "isPopular": True},
    {"id": 3, "name": "鮮榨檸檬汁", "price": 55, "category": "fruit-tea", "isPopular": False},
    {"id": 4, "name": "草莓優格冰沙", "price": 85, "category": "seasonal", "isPopular": False},
]


# --- API 端點定義 ---

@app.route('/api/menu', methods=['GET'])
def get_menu():
    """
    [GET] 取得完整的菜單列表
    """
    return jsonify(MENU_ITEMS)

@app.route('/api/order', methods=['POST'])
def place_order():
    """
    [POST] 接收前端傳來的訂單資料
    """
    
    if not request.is_json:
        return jsonify({"message": "Missing JSON in request"}), 400

    data = request.get_json()

    if 'cartItems' not in data or 'contactInfo' not in data:
        return jsonify({"message": "Invalid order data structure"}), 400
        
    # 1. 計算訂單總金額
    total_amount = 0
    for item in data['cartItems']:
        total_amount += item.get('price', 0) * item.get('quantity', 0)
    
    # 2. 計算運費與最終金額
    DELIVERY_FEE = 50 if data.get('pickupType') == 'delivery' else 0
    final_amount = total_amount + DELIVERY_FEE

    # 3. 處理訂單編號
    last_order = Order.query.order_by(Order.order_id.desc()).first()
    new_order_id = 1001 
    if last_order:
        new_order_id = last_order.order_id + 1
    
    # 4. 處理聯絡資訊與地址
    contact_info = data.get('contactInfo', {})
    contact_name = contact_info.get('name', 'N/A')
    contact_phone = contact_info.get('phone', 'N/A')
    delivery_address = contact_info.get('address')
    pickup_type = data.get('pickupType', 'pickup')
    
    if delivery_address:
         delivery_address = delivery_address.strip()
    if delivery_address == "":
         delivery_address = None

    # VVVV 5. 儲存 ContactInfo 實體 VVVV
    new_contact = ContactInfo(
        contact_name=contact_name,
        contact_phone=contact_phone,
        delivery_address=delivery_address,
        pickup_type=pickup_type
    )
    db.session.add(new_contact)
    db.session.flush() # 獲取 new_contact 的 ID
    # ^^^^ 5. 儲存 ContactInfo 實體 ^^^^


    # 6. 建立 Order 實體
    new_db_order = Order(
        order_id=new_order_id,
        status="pending",
        final_amount=final_amount,
        items_json=json.dumps(data['cartItems']),
        contact_id=new_contact.id # 使用外鍵 ID
    )

    # 提交到資料庫
    try:
        db.session.add(new_db_order)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Database error: {e}")
        return jsonify({"message": "Database insertion failed"}), 500

    return jsonify({
        "message": "Order placed successfully!",
        "order_id": new_db_order.order_id,
        "final_amount": new_db_order.final_amount,
        "estimated_pickup_time": "Time calculation removed for simplicity, or use calculated time here"
    }), 201

@app.route('/api/orders/all', methods=['GET'])
def get_all_orders():
    """
    [GET] 取得所有訂單，回傳後台所需資訊。
    """
    
    # 使用 joinedload 預先載入 ContactInfo，減少資料庫查詢次數
    orders = Order.query.options(db.joinedload(Order.contact)).order_by(Order.id.desc()).all()
    
    orders_list = []
    for order in orders:
        
        # VVVV 從 ContactInfo 實體獲取聯絡人資訊 VVVV
        contact = order.contact
        customer_name = contact.contact_name
        phone_full = contact.contact_phone if contact.contact_phone else "N/A"
        phone_last_three = phone_full 
        
        # 處理訂單內容 (items_json)
        try:
            items_data = json.loads(order.items_json)
            content_summary = []
            for item in items_data:
                options = item.get('options', '').split(' / ')[0] 
                summary = f"{item.get('name', '未知飲品')} ({options}) x {item.get('quantity', 1)}"
                content_summary.append(summary)
            order_content = ", ".join(content_summary)
        except:
            order_content = "無法解析訂單內容"
            
        
        orders_list.append({
            "order_id": order.id,
            "content": order_content,
            "final_amount": order.final_amount,
            "customer_name": customer_name,
            "contact_phone_last_three": phone_last_three,
            "status": order.status,
            "pickup_type": contact.pickup_type, # 從 ContactInfo 獲取
            "delivery_address": contact.delivery_address, # 從 ContactInfo 獲取
            "created_at": order.created_at.isoformat(),
        })
        
    return jsonify(orders_list)

@app.route('/api/order/query', methods=['GET'])
def query_order_by_phone():
    """
    [GET] 根據手機後三碼查詢訂單狀態。
    """
    phone_suffix = request.args.get('phone_suffix')
    
    if not phone_suffix or len(phone_suffix) != 3 or not phone_suffix.isdigit():
        return jsonify({"message": "請提供正確的 3 位數字手機後三碼進行查詢。"}), 400

    # VVVV 查詢：先找到匹配的 ContactInfo，再用其 ID 查詢 Order VVVV
    contacts = ContactInfo.query.filter(ContactInfo.contact_phone == phone_suffix).all()
    if not contacts:
        return jsonify({"message": "查無訂單，請確認手機後三碼是否正確。"}), 404
    
    contact_ids = [c.id for c in contacts]
    
    orders = Order.query.filter(Order.contact_id.in_(contact_ids)).order_by(Order.created_at.desc()).all()
    # ^^^^ 查詢 ^^^^

    result_list = []
    for order in orders:
        contact = order.contact # 透過關係屬性訪問聯絡資訊
        
        # 處理訂單內容
        try:
            items_data = json.loads(order.items_json)
            content_summary = []
            for item in items_data:
                content_summary.append(f"{item.get('name', '飲品')} x {item.get('quantity', 1)}")
            order_content = ", ".join(content_summary)
        except:
            order_content = "無法解析訂單內容"
            
        result_list.append({
            "order_id": order.order_id,
            "content": order_content,
            "final_amount": order.final_amount,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "pickup_type": contact.pickup_type,      
            "address": contact.delivery_address      
        })
        
    return jsonify(result_list)


@app.route('/api/order/<int:order_id>', methods=['GET'])
def get_order_status(order_id):
    """
    [GET] 根據訂單 ID 查詢訂單狀態
    """
    # 此 API 未被前端使用，邏輯上應被 order/query 取代，暫時保留
    return jsonify({"message": "API Not Implemented"}), 404

@app.route('/api/orders/clear', methods=['POST'])
def clear_all_orders():
    """
    [POST] 清空所有訂單和聯絡人記錄，並重設訂單編號。
    """
    try:
        # 1. 刪除所有訂單記錄
        db.session.query(Order).delete(synchronize_session='fetch')
        # 2. 刪除所有聯絡人記錄
        db.session.query(ContactInfo).delete(synchronize_session='fetch')
        
        # 3. 提交變更
        db.session.commit()
        
        return jsonify({
            "message": "成功刪除所有訂單和聯絡人記錄，訂單編號將從 1001 開始。",
            "deleted_count": 0
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"清空訂單失敗: {e}")
        return jsonify({"message": f"清空訂單失敗: {e}"}), 500


# --- 運行應用程式 ---
with app.app_context(): 
    db.create_all()