from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import math
import os
import uuid
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from werkzeug.utils import secure_filename

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# ワークショップ課題：青森市の市区町村コードに変更する
AREA_CODE = "0220100"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
DRAFT_FILE = os.path.join(APP_DIR, 'data', 'shelter_draft.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
NOTIFICATION_FILE = os.path.join(APP_DIR, 'data', 'notification_history.json')
SAFETY_FILE = os.path.join(APP_DIR, 'data', 'family_safety.json')
UPLOAD_DIR = os.path.join(app.static_folder, 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
LIVE_CAMPUS_URL = 'https://livecampus.jp/'

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
family_safety = load_json(SAFETY_FILE, [])
shelter_draft = load_json(DRAFT_FILE, {})

SUPPORTED_DISASTERS = {'地震', '洪水', '土砂災害', '津波', '高潮', '火災'}
FACILITIES = {
    'トイレ', '多目的トイレ', '飲料水', '非常食', 'Wi-Fi', '充電設備・電源',
    'AED', '救護スペース', '車椅子対応（バリアフリー）', '乳幼児・授乳スペース',
    'ペット受入可', '外国語対応'
}
OPENING_STATUSES = {'未開設', '開設中', '閉鎖'}

def save_family_safety():
    """家族の安否確認データをファイルに保存する"""
    try:
        with open(SAFETY_FILE, 'w', encoding='utf-8') as f:
            json.dump(family_safety, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def save_notifications(notifications):
    """通報内容をファイルに保存する"""
    try:
        with open(NOTIFICATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(notifications, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def save_shelters():
    """避難所データをファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def save_shelter_draft():
    try:
        with open(DRAFT_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelter_draft, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def save_shelter_photo(photo):
    """アップロードされた避難所写真を保存して静的URLを返す"""
    if not photo or not photo.filename:
        return None
    extension = os.path.splitext(secure_filename(photo.filename))[1].lower().lstrip('.')
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{extension}'
    photo.save(os.path.join(UPLOAD_DIR, filename))
    return f'/static/uploads/{filename}'

def parse_nonnegative_int(value, default=0):
    """値を0以上の整数に変換する"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default

def parse_coordinate(value, minimum, maximum):
    """緯度・経度を範囲検証して返す"""
    try:
        coordinate = float(value)
        if minimum <= coordinate <= maximum:
            return coordinate
    except (TypeError, ValueError):
        pass
    return None

def has_facility(shelter, facility):
    """旧辞書形式と新配列形式の設備を共通判定する"""
    facilities = shelter.get('facilities', {})
    if isinstance(facilities, dict):
        return bool(facilities.get(facility))
    return facility in facilities
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、解除済み以外を返す"""
    return [
        s for s in shelters
        if s.get('status', 'active') != 'inactive'
        and (not district or s.get('district') == district)
    ]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 住民からの通報フォーム
@app.route('/report', methods=['GET', 'POST'])
def report():
    if request.method == 'POST':
        district = request.form.get('district', '').strip() or '市内全域'
        reporter_type = request.form.get('reporter_type', '').strip()
        occurred_at = request.form.get('occurred_at', '').strip()
        damage_type = request.form.get('damage_type', '').strip()
        other_content = request.form.get('other_content', '').strip()
        latitude = parse_coordinate(request.form.get('lat', '').strip(), -90, 90)
        longitude = parse_coordinate(request.form.get('lng', '').strip(), -180, 180)
        photo_url = save_shelter_photo(request.files.get('photo'))
        form_data = {'district': district, 'reporter_type': reporter_type, 'occurred_at': occurred_at, 'damage_type': damage_type, 'other_content': other_content, 'lat': request.form.get('lat', '').strip(), 'lng': request.form.get('lng', '').strip()}
        if reporter_type not in {'個人', '施設'}:
            return render_template('report.html', error='通報元を選択してください。', form_data=form_data)
        if not occurred_at:
            return render_template('report.html', error='発生時刻を選択してください。', form_data=form_data)
        if damage_type not in {'火事', '建物倒壊', '道路通行止め', '人災', 'その他'}:
            return render_template('report.html', error='被害内容を選択してください。', form_data=form_data)
        if damage_type == 'その他' and not other_content:
            return render_template('report.html', error='その他の被害内容を入力してください。', form_data=form_data)
        if request.files.get('photo') and request.files['photo'].filename and photo_url is None:
            return render_template('report.html', error='写真は画像ファイル（jpg、png、gif、webp）を選択してください。', form_data=form_data)

        notifications = load_json(NOTIFICATION_FILE, [])
        now = get_japan_time()
        content = f'通報元: {reporter_type} / 発生時刻: {occurred_at} / 被害内容: {other_content if damage_type == "その他" else damage_type}'
        new_report = {
            'id': max([item.get('id', 0) for item in notifications if isinstance(item.get('id', 0), int)], default=0) + 1,
            'timestamp': now,
            'district': district,
            'content': content,
            'reporter_type': reporter_type,
            'occurred_at': occurred_at,
            'damage_type': damage_type,
            'status': '未確認'
        }
        if latitude is not None and longitude is not None:
            new_report.update({'lat': latitude, 'lng': longitude})
        if photo_url:
            new_report['photo_url'] = photo_url
        notifications.insert(0, new_report)
        if save_notifications(notifications):
            return render_template('report.html', success='通報を送信しました。')
        return render_template('report.html', error='通報の保存に失敗しました。', form_data=form_data)

    return render_template('report.html')

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        # フォームから入力データを取得
        name = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        district = request.form.get('district', '').strip()
        capacity = request.form.get('capacity', '').strip()
        photo = request.files.get('photo')
        photo_url = save_shelter_photo(photo)
        if photo and photo.filename and photo_url is None:
            return render_template('shelter_register.html', error=True, message='写真は画像ファイル（jpg、png、gif、webp）を選択してください。')
        damage_status = request.form.get('damage_status', '').strip() or '未確認'
        evacuee_count = request.form.get('evacuee_count', '').strip()
        action = request.form.get('action', 'save')
        supported_disasters = [item for item in request.form.getlist('supported_disasters') if item in SUPPORTED_DISASTERS]
        facilities = [item for item in request.form.getlist('facilities') if item in FACILITIES]
        opening_status = request.form.get('opening_status', '').strip()
        shelter_id = request.form.get('shelter_id', '').strip()
        latitude = parse_coordinate(request.form.get('lat', '').strip(), -90, 90)
        longitude = parse_coordinate(request.form.get('lng', '').strip(), -180, 180)

        form_data = {
            'name': name, 'address': address, 'phone': phone, 'district': district, 'capacity': capacity,
            'status': 'active', 'damage_status': damage_status,
            'evacuee_count': evacuee_count, 'shelter_id': shelter_id,
            'lat': request.form.get('lat', '').strip(), 'lng': request.form.get('lng', '').strip(),
            'supported_disasters': supported_disasters, 'facilities': facilities,
            'opening_status': opening_status
        }
        if photo_url:
            form_data['photo_url'] = photo_url
        if action == 'draft':
            shelter_draft.clear()
            shelter_draft.update(form_data)
            message = '入力内容を一時保存しました。'
            if save_shelter_draft():
                return render_template('shelter_register.html', success=True, message=message, form_data=form_data)
            return render_template('shelter_register.html', error=True, message='一時保存に失敗しました。', form_data=form_data)
        if not name:
            return render_template('shelter_register.html', error=True, message='避難所名を入力してください。', form_data=form_data)
        if not address:
            return render_template('shelter_register.html', error=True, message='住所を入力してください。', form_data=form_data)
        if not phone:
            return render_template('shelter_register.html', error=True, message='電話番号を入力してください。', form_data=form_data)
        if not capacity or not capacity.isdigit():
            return render_template('shelter_register.html', error=True, message='収容人数は0以上の整数で入力してください。', form_data=form_data)
        if opening_status not in OPENING_STATUSES:
            return render_template('shelter_register.html', error=True, message='開設状況を選択してください。', form_data=form_data)
        
        existing = next((s for s in shelters if str(s.get('id')) == shelter_id), None)
        if existing:
            existing.update({
                'name': name,
                'location': address or existing.get('address', existing.get('location', '')),
                'address': address or existing.get('address', ''),
                'district': district or existing.get('district', ''),
                'phone': phone or existing.get('phone', ''),
                'status': 'active',
                'damage_status': damage_status,
                'evacuee_count': parse_nonnegative_int(evacuee_count, existing.get('evacuee_count', 0)),
                'capacity': parse_nonnegative_int(capacity, existing.get('capacity', 0)),
                'supported_disasters': supported_disasters,
                'opening_status': opening_status,
                'facilities': facilities
            })
            if photo_url:
                existing['photo_url'] = photo_url
            if latitude is not None and longitude is not None:
                existing.update({'lat': latitude, 'lng': longitude})
        else:
            max_id = max([s.get('id', 0) for s in shelters], default=0)
            new_shelter = {
                'id': max_id + 1,
                'name': name,
                'status': 'active',
                'location': address,
                'address': address,
                'district': district,
                'phone': phone,
                'damage_status': damage_status,
                'evacuee_count': parse_nonnegative_int(evacuee_count),
                'capacity': parse_nonnegative_int(capacity),
                'supported_disasters': supported_disasters,
                'opening_status': opening_status,
                'facilities': facilities
            }
            if photo_url:
                new_shelter['photo_url'] = photo_url
            if latitude is not None and longitude is not None:
                new_shelter.update({'lat': latitude, 'lng': longitude})
            shelters.append(new_shelter)
        
        # ファイルに保存
        if save_shelters():
            shelter_draft.clear()
            save_shelter_draft()
            return redirect(url_for('shelter_status', message='登録完了しました。'))
        else:
            return render_template('shelter_register.html', 
                                 error=True, 
                                 message="登録に失敗しました。もう一度試してください。")
    
    edit_id = request.args.get('shelter_id')
    edit_shelter = next(
        (s for s in shelters if str(s.get('id')) == edit_id), None
    ) if edit_id else None
    if edit_id and edit_shelter is None:
        return '避難所が見つかりません', 404
    return render_template(
        'shelter_register.html',
        shelter=edit_shelter,
        form_data=shelter_draft if not edit_shelter else {}
    )

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    visible_shelters = shelters if session.get('logged_in') else filter_shelters()
    return render_template('shelter_search.html', shelters=visible_shelters)

# 家族の安否確認ページ
@app.route('/safety_confirmation', methods=['GET', 'POST'])
def safety_confirmation():
    if request.method == 'POST':
        member_id = request.form.get('member_id', '')
        status = request.form.get('status', '')
        phone = request.form.get('phone', '').strip()
        allowed_statuses = {'無事', '避難中', '未確認'}

        for member in family_safety:
            if str(member.get('id')) == member_id and status in allowed_statuses:
                member['status'] = status
                member['phone'] = phone
                save_family_safety()
                break

    return render_template('safety_confirmation.html', family_safety=family_safety)

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    visible_shelters = shelters if session.get('logged_in') else filter_shelters()
    return render_template('search_results.html', results=visible_shelters, message=request.args.get('message'))

# 避難所の状況を一覧で確認する管理者向け画面
@app.route('/shelter_status')
@login_required
def shelter_status():
    return render_template('shelter_status.html', shelters=shelters)

@app.route('/shelter_delete/<int:shelter_id>', methods=['POST'])
@login_required
def shelter_delete(shelter_id):
    index = next((i for i, shelter in enumerate(shelters) if shelter.get('id') == shelter_id), None)
    if index is None:
        return '避難所が見つかりません', 404
    deleted = shelters.pop(index)
    if not save_shelters():
        shelters.insert(index, deleted)
        return render_template('search_results.html', results=filter_shelters(), message='避難所の削除に失敗しました。'), 500
    return redirect(url_for('all_shelters', message='避難所情報を削除しました。'))


# 指示ボード：住民向けの指示を一覧で確認する
BOARD_DISTRICTS = ['市内全域', '北地区', '南地区', '東地区', '西地区', '中央地区', '浪岡地区']

def board_district(value):
    return value if value in BOARD_DISTRICTS else '市内全域'

def damage_index(report):
    """通報内容から0.0〜10.0の被害指数を算出する"""
    for key in ('damage_index', 'damage_scale', 'damage_level'):
        try:
            return round(max(0.0, min(10.0, float(report.get(key)))), 1)
        except (TypeError, ValueError):
            pass

    content = str(report.get('content', report.get('warnings', '')) or '')
    severity_scores = (
        (('死者', '倒壊', '使用不可', '通行止め'), 9.0),
        (('大きな被害', '浸水', '冠水', '土砂', '負傷'), 7.0),
        (('倒木', '停電', 'あふれ', '水位が上昇'), 5.0),
        (('被害', '危険', '注意'), 3.0),
    )
    return max((score for words, score in severity_scores if any(word in content for word in words)), default=0.0)

def report_photo_url(report):
    """通報に含まれる写真URLを取得する"""
    for key in ('photo_url', 'photo', 'image_url', 'attachment_url'):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    return None

@app.route('/board', methods=['GET', 'POST'])
@login_required
def board():
    if request.method == 'POST':
        target = request.form.get('target', '')
        districts = [board_district(item) for item in request.form.getlist('district')]
        content = request.form.get('content', '').strip()
        if target not in {'住民', '職員'}:
            return render_template('board.html', error='発信対象を選択してください。', **board_context())
        if not content:
            return render_template('board.html', error='指示内容を入力してください。', **board_context())
        district = next((item for item in districts if item != '市内全域'), '市内全域')
        now = get_japan_time()
        new_instruction = {
            'id': max([item.get('id', 0) for item in instructions if isinstance(item.get('id', 0), int)], default=0) + 1,
            'target': target,
            'district': district,
            'content': content,
            'status': '発信中',
            'shelter': '',
            'created_at': now,
            'updated_at': now
        }
        instructions.insert(0, new_instruction)
        if save_instructions():
            return redirect(url_for('board', message='指示を登録しました。'))
        instructions.pop(0)
        return render_template('board.html', error='指示の保存に失敗しました。', **board_context())

    return render_template('board.html', message=request.args.get('message'), **board_context())

@app.route('/notices')
def notices():
    visible_notices = sorted(
        instructions,
        key=lambda item: item.get('updated_at', item.get('created_at', '')),
        reverse=True
    )
    return render_template('notices.html', notices=visible_notices)

def board_context():
    selected = board_district(request.args.get('district'))
    visible_instructions = sorted(
        [item for item in instructions if selected == '市内全域' or board_district(item.get('district')) == selected],
        key=lambda item: item.get('updated_at', item.get('created_at', '')),
        reverse=True
    )
    reports = load_json(os.path.join(APP_DIR, 'data', 'notification_history.json'), [])
    visible_reports = sorted(
        [item for item in reports if selected == '市内全域' or board_district(item.get('district', item.get('area_name'))) == selected],
        key=lambda item: item.get('timestamp', item.get('created_at', '')),
        reverse=True
    )
    for report in visible_reports:
        report['_damage_index'] = damage_index(report)
        report['_photo_url'] = report_photo_url(report)
    return {
        'instructions': visible_instructions,
        'reports': visible_reports,
        'districts': BOARD_DISTRICTS,
        'selected_district': selected
    }

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results = filter_shelters(request.args.get('district'))
    name = request.args.get('name', '').strip().lower()
    location = request.args.get('location', '').strip().lower()
    if name or location:
        results = [
            shelter for shelter in results
            if (not name or name in str(shelter.get('name', '') or '').lower())
            and (not location or location in str(shelter.get('location', shelter.get('address', '')) or '').lower())
        ]
    facilities = request.args.getlist('facility')
    if facilities:
        results = [
            shelter for shelter in results
            if all(has_facility(shelter, facility) for facility in facilities)
        ]
    return render_template('search_results.html', results=results)

@app.route('/api/geocode')
def api_geocode():
    """所在地を地図座標へ変換する（結果は保存しない）"""
    address = request.args.get('address', '').strip()
    if not address:
        return jsonify({'error': '住所がありません'}), 400
    try:
        url = 'https://nominatim.openstreetmap.org/search?' + urlencode({
            'q': address,
            'format': 'jsonv2',
            'limit': 1
        })
        request_obj = urllib.request.Request(
            url,
            headers={'User-Agent': 'bousai-app-shelter-search/1.0'}
        )
        with urllib.request.urlopen(request_obj, timeout=5) as response:
            candidates = json.loads(response.read())
        if not candidates:
            return jsonify({'error': '所在地を検索できませんでした'}), 404
        latitude = parse_coordinate(candidates[0].get('lat'), -90, 90)
        longitude = parse_coordinate(candidates[0].get('lon'), -180, 180)
        if latitude is None or longitude is None:
            return jsonify({'error': '有効な座標がありません'}), 404
        return jsonify({'lat': latitude, 'lng': longitude})
    except Exception:
        return jsonify({'error': '所在地の検索に失敗しました'}), 502

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

@app.route('/api/shelters')
def api_shelters():
    """避難所データをJSON形式で返すAPI"""
    return jsonify(filter_shelters())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
