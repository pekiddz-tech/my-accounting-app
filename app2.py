import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 設定頁面
st.set_page_config(page_title="雲端記帳 App", layout="centered")

# --- 設定區 ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1MdOuH0QUDQko6rzZxf94d2SK3dHsnQKav_luJLCJhEo/edit?gid=0#gid=0" 

# --- CSS 優化 ---
st.markdown("""
<style>
    div[data-testid="column"] { min-width: 0 !important; flex: 1 !important; padding: 0 5px !important; }
    .stButton button { width: 100%; font-weight: bold !important; }
    .lcd-screen {
        background-color: #262730; color: #00FF41; padding: 15px; 
        border-radius: 8px; text-align: right; font-size: 32px; 
        font-family: 'Courier New', monospace; font-weight: bold; 
        margin-top: 5px; margin-bottom: 15px; border: 2px solid #555;
        box-shadow: inset 0 0 10px #000; text-shadow: 0 0 5px #00FF41;
    }
    .lcd-label { color: #888; font-size: 12px; text-align: right; margin-bottom: -10px; margin-right: 5px; }
</style>
""", unsafe_allow_html=True)

# --- 1. 連線 Google Sheets (加入快取，讓速度變快！) ---
@st.cache_resource(ttl=600) # 快取連線物件，避免每次按按鈕都重新連線
def connect_to_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SHEET_URL).sheet1
        return sheet
    except Exception as e:
        st.error(f"連線失敗: {e}")
        return None

# 讀取資料不快取，因為需要即時更新
def load_data():
    sheet = connect_to_sheet()
    if sheet:
        try:
            data = sheet.get_all_records()
            df = pd.DataFrame(data)
            if df.empty: return pd.DataFrame(columns=['日期', '購物細項', '金額'])
            df['日期'] = pd.to_datetime(df['日期']).dt.date
            return df
        except: return pd.DataFrame(columns=['日期', '購物細項', '金額'])
    return pd.DataFrame(columns=['日期', '購物細項', '金額'])

# 存檔函數
def save_data_to_sheet(df):
    sheet = connect_to_sheet()
    if sheet:
        df_to_save = df.copy()
        df_to_save['日期'] = df_to_save['日期'].astype(str)
        sheet.clear()
        sheet.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())

# --- 2. 核心邏輯函數 ---
def safe_calculate(expression):
    try:
        allowed = "0123456789.+-*/() "
        if not all(c in allowed for c in str(expression)): return 0
        return float(eval(str(expression)))
    except: return 0

# --- 🆕 關鍵：新增資料的回呼函數 (Callback) ---
def add_record_callback():
    # 從 session_state 抓取目前輸入的值
    date_val = st.session_state.date_input
    item_val = st.session_state.input_item
    amount_str = st.session_state.input_amount
    
    # 計算金額
    calc_val = safe_calculate(amount_str)
    
    if item_val and calc_val > 0:
        # 1. 讀取舊資料
        current_df = load_data()
        
        # 2. 建立新資料
        new_row = pd.DataFrame({
            '日期': [date_val],
            '購物細項': [item_val],
            '金額': [int(calc_val)]
        })
        
        # 3. 合併並存檔
        updated_df = pd.concat([current_df, new_row], ignore_index=True)
        save_data_to_sheet(updated_df)
        
        # 4. 設定成功訊息與音效觸發 (存入 Session State 供下一次渲染使用)
        st.session_state.success_msg = f"已儲存：{item_val} ${int(calc_val)}"
        st.session_state.trigger_sound_play = True
        
        # 5. ✨ 直接清空輸入欄位 (這就是順暢的關鍵)
        st.session_state.input_item = ""
        st.session_state.input_amount = ""
        
    elif calc_val == 0 and amount_str:
        st.session_state.error_msg = "算式錯誤，請檢查輸入"
    else:
        st.session_state.error_msg = "請輸入完整的項目名稱與金額"

# --- 3. Excel 匯出 ---
def generate_custom_excel(df):
    output = io.BytesIO()
    if df.empty: return None
    df = df.copy()
    df['dt'] = pd.to_datetime(df['日期'])
    df['Year'] = df['dt'].dt.year
    df['Month'] = df['dt'].dt.month
    df['Day'] = df['dt'].dt.day
    target_year = df['Year'].max()
    year_df = df[df['Year'] == target_year]

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        sheet = workbook.add_worksheet('年度支出清冊')
        fmt_header = workbook.add_format({'bold': True, 'align': 'center', 'border': 1, 'bg_color': '#D9E1F2'})
        fmt_date = workbook.add_format({'align': 'center', 'border': 1})
        fmt_text = workbook.add_format({'text_wrap': True, 'border': 1, 'valign': 'top'})
        fmt_money = workbook.add_format({'num_format': '#,##0', 'border': 1})
        fmt_total = workbook.add_format({'bold': True, 'bg_color': '#FCE4D6', 'num_format': '#,##0', 'border': 1})
        fmt_title = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        sheet.merge_range('A1:G1', f'{target_year}年 支出清冊', fmt_title)
        current_row = 2
        grand_total = 0
        for q in range(4):
            start_month = q * 3 + 1
            months = [start_month, start_month+1, start_month+2]
            headers = ['日期']
            for m in months: headers.extend([f'{m}月摘要', '金額'])
            for col_num, header in enumerate(headers): sheet.write(current_row, col_num, header, fmt_header)
            sheet.set_column(0, 0, 5); sheet.set_column(1, 1, 30); sheet.set_column(2, 2, 12)
            sheet.set_column(3, 3, 30); sheet.set_column(4, 4, 12); sheet.set_column(5, 5, 30); sheet.set_column(6, 6, 12)
            current_row += 1
            col_totals = {m: 0 for m in months}
            for day in range(1, 32):
                sheet.write(current_row, 0, day, fmt_date)
                for i, m in enumerate(months):
                    day_data = year_df[(year_df['Month'] == m) & (year_df['Day'] == day)]
                    if not day_data.empty:
                        desc_list = []
                        day_sum = 0
                        for _, row in day_data.iterrows():
                            desc_list.append(f"{row['購物細項']}{int(row['金額'])}")
                            day_sum += row['金額']
                        desc_str = " ".join(desc_list)
                        sheet.write(current_row, 1 + i*2, desc_str, fmt_text)
                        sheet.write(current_row, 2 + i*2, day_sum, fmt_money)
                        col_totals[m] += day_sum
                current_row += 1
            sheet.write(current_row, 0, "合計", fmt_total)
            for i, m in enumerate(months):
                sheet.write(current_row, 1 + i*2, "本月小計", fmt_total)
                sheet.write(current_row, 2 + i*2, col_totals[m], fmt_total)
                grand_total += col_totals[m]
            current_row += 3
        sheet.merge_range(current_row, 0, current_row, 1, '年度總支出', fmt_title)
        sheet.write(current_row, 2, grand_total, fmt_total)
    return output

# --- 4. App 介面開始 ---
st.title("💰 DRKKY雲端記帳本")

# --- 音效處理 ---
SOUND_MAP = {
    "無聲": None,
    "🔔 清脆叮聲": "https://www.soundjay.com/buttons/sounds/button-3.mp3",
    "💰 收銀機聲": "https://www.soundjay.com/misc/sounds/coins-in-hand-2.mp3",
    "🎮 遊戲過關": "https://www.soundjay.com/human/sounds/applause-01.mp3",
    "🪙 金幣掉落": "https://www.soundjay.com/misc/sounds/magic-chime-01.mp3",
    "✨ 魔法音效": "https://www.soundjay.com/misc/sounds/bell-ringing-05.mp3",
    "🎹 鋼琴和弦": "https://www.soundjay.com/buttons/sounds/button-10.mp3"
}

# 處理音效播放與訊息顯示 (放在最上面)
if st.session_state.get('trigger_sound_play'):
    sound_url = st.session_state.get('selected_sound_url')
    if sound_url:
        st.markdown(f'<audio autoplay style="display:none;"><source src="{sound_url}" type="audio/mpeg"></audio>', unsafe_allow_html=True)
    st.session_state.trigger_sound_play = False

if st.session_state.get('success_msg'):
    st.success(st.session_state.success_msg)
    st.session_state.success_msg = None # 顯示完清空

if st.session_state.get('error_msg'):
    st.error(st.session_state.error_msg)
    st.session_state.error_msg = None

# --- 設定區 ---
with st.expander("⚙️ 設定 (音效與其他)"):
    selected_sound_name = st.selectbox("選擇確認新增時的音效", list(SOUND_MAP.keys()), index=1)
    st.session_state.selected_sound_url = SOUND_MAP[selected_sound_name]

# 載入資料
df = load_data()

tab_manual, tab_import = st.tabs(["📝 手動記帳", "☁️ 匯入雲端發票"])

# === 功能一：手動記帳 (使用 Callback 模式) ===
with tab_manual:
    # 這裡綁定 key="date_input"，讓 callback 可以抓到值
    date_input = st.date_input("選擇日期", datetime.now(), key="date_input")
    
    col1, col2 = st.columns([2, 1.2])
    with col1:
        # 這裡綁定 key="input_item"
        if "input_item" not in st.session_state: st.session_state.input_item = ""
        st.text_input("購物細項", placeholder="例如：午餐", key="input_item")
        
    with col2:
        # 這裡綁定 key="input_amount"
        if "input_amount" not in st.session_state: st.session_state.input_amount = ""
        amount_input = st.text_input("輸入金額或算式", placeholder="如: 50+20", key="input_amount")

    # 即時計算 LCD
    preview_val = safe_calculate(amount_input)
    display_text = f"{int(preview_val)}" if preview_val > 0 else "0"

    st.markdown(f'<div class="lcd-label">Total Amount</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="lcd-screen">{display_text}</div>', unsafe_allow_html=True)

    # 🆕 按鈕使用 on_click 呼叫 callback，不直接寫邏輯
    st.button("✅ 確認新增", type="primary", use_container_width=True, on_click=add_record_callback)

# === 功能二：匯入雲端發票 ===
with tab_import:
    st.markdown("### 批次匯入發票 CSV")
    uploaded_file = st.file_uploader("選擇 CSV 檔案", type=['csv'])
    if uploaded_file is not None:
        try:
            try: import_df = pd.read_csv(uploaded_file, encoding='utf-8')
            except: import_df = pd.read_csv(uploaded_file, encoding='cp950')
            all_columns = import_df.columns.tolist()
            c1, c2, c3 = st.columns(3)
            with c1: col_date = st.selectbox("日期欄位", all_columns)
            with c2: col_item = st.selectbox("品名欄位", all_columns, index=1)
            with c3: col_amount = st.selectbox("金額欄位", all_columns, index=2)

            if st.button("🚀 確認匯入"):
                new_records = []
                for index, row in import_df.iterrows():
                    try:
                        d = pd.to_datetime(row[col_date]).date()
                        item_name = str(row[col_item])
                        if "(雲端發票)" not in item_name: item_name = f"{item_name}(雲端發票)"
                        amt = float(str(row[col_amount]).replace(',', '').replace('$', ''))
                        if amt > 0:
                            new_records.append({'日期': d, '購物細項': item_name, '金額': int(amt)})
                    except: continue
                if new_records:
                    new_df = pd.DataFrame(new_records)
                    df = pd.concat([load_data(), new_df], ignore_index=True)
                    save_data_to_sheet(df)
                    st.session_state.success_msg = f"成功匯入 {len(new_records)} 筆！"
                    st.session_state.trigger_sound_play = True
                    st.rerun()
        except Exception as e: st.error(f"錯誤：{e}")

# --- 5. 數據統計與顯示 ---
st.markdown("---")
st.subheader("📊 帳務總覽")

if not df.empty:
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    
    tab_specific, tab_today, tab_week, tab_month, tab_custom = st.tabs(
        ["📅 特定日期", "☀️ 今日", "🗓️ 本周", "📊 本月", "🔍 自訂區間"]
    )
    
    def display_filtered_records(filtered_df, tab_name):
        if filtered_df.empty:
            st.info(f"{tab_name} 目前沒有消費記錄。")
        else:
            total_amount = filtered_df['金額'].sum()
            st.metric(label=f"{tab_name} 總支出", value=f"${total_amount:,}")
            st.write("📋 **詳細清單**")
            display_df = filtered_df.sort_values('日期', ascending=False).reset_index()
            h1, h2, h3, h4 = st.columns([2.5, 3.5, 2, 2])
            h1.write("**日期**"); h2.write("**項目**"); h3.write("**金額**"); h4.write("**操作**")

            for i, row in display_df.iterrows():
                c1, c2, c3, c4 = st.columns([2.5, 3.5, 2, 2])
                c1.write(f"{row['日期']}")
                c2.write(f"{row['購物細項']}")
                c3.write(f"${row['金額']}")
                unique_key = f"del_{tab_name}_{row['index']}"
                if c4.button("刪除", key=unique_key, type="secondary"):
                    save_data_to_sheet(df.drop(row['index']))
                    st.warning(f"已刪除：{row['購物細項']}")
                    st.rerun()

    with tab_specific:
        st.write("選擇想查詢的那一天：")
        target_date = st.date_input("查詢日期", today)
        df_target = df[df['日期'] == target_date]
        st.markdown("---")
        display_filtered_records(df_target, f"{target_date}")

    with tab_today:
        df_today = df[df['日期'] == today]
        display_filtered_records(df_today, "今日")

    with tab_week:
        df_week = df[df['日期'] >= start_of_week]
        display_filtered_records(df_week, "本周")

    with tab_month:
        df['dt_temp'] = pd.to_datetime(df['日期'])
        df_month = df[(df['dt_temp'].dt.year == today.year) & (df['dt_temp'].dt.month == today.month)]
        display_filtered_records(df_month, "本月")
    
    with tab_custom:
        st.write("選擇起始與結束日期：")
        d_col1, d_col2 = st.columns(2)
        with d_col1: start_date = st.date_input("開始日期", today.replace(day=1))
        with d_col2: end_date = st.date_input("結束日期", today)
        if start_date > end_date: st.error("開始日期不能晚於結束日期！")
        else:
            df_range = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]
            st.markdown("---")
            display_filtered_records(df_range, "搜尋區間")

    st.markdown("---")
    excel_data = generate_custom_excel(df)
    if excel_data:
        st.download_button("下載年度清冊 (.xlsx)", excel_data.getvalue(), f'年度支出_{datetime.now().strftime("%Y%m%d")}.xlsx', "application/vnd.ms-excel")
else:
    st.info("目前還沒有資料。")