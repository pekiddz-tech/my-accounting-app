import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 設定頁面
st.set_page_config(page_title="雲端記帳 App", layout="centered")

# --- 設定區 (請修改這裡) ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/xxxxxxxxxxxxxxxx/edit" # <--- 記得換回你的網址

# --- 1. 連線 Google Sheets 函數 ---
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

def load_data():
    sheet = connect_to_sheet()
    if sheet:
        try:
            data = sheet.get_all_records()
            df = pd.DataFrame(data)
            if df.empty:
                return pd.DataFrame(columns=['日期', '購物細項', '金額'])
            # 確保日期格式正確
            df['日期'] = pd.to_datetime(df['日期']).dt.date
            return df
        except Exception:
            return pd.DataFrame(columns=['日期', '購物細項', '金額'])
    return pd.DataFrame(columns=['日期', '購物細項', '金額'])

def save_data(df):
    sheet = connect_to_sheet()
    if sheet:
        df_to_save = df.copy()
        df_to_save['日期'] = df_to_save['日期'].astype(str)
        sheet.clear()
        sheet.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())

# --- 2. 輔助功能：計算機邏輯 ---
def safe_calculate(expression):
    """
    將字串算式 (例如 '100+50*2') 轉換為數字
    """
    allowed_chars = "0123456789.+-*/() "
    if not all(char in allowed_chars for char in expression):
        return None
    try:
        # 使用 eval 計算，但只允許數學運算
        return eval(expression)
    except:
        return None

# --- 3. 核心功能：Excel 匯出 (維持不變) ---
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
            
            sheet.set_column(0, 0, 5)
            sheet.set_column(1, 1, 30)
            sheet.set_column(2, 2, 12)
            sheet.set_column(3, 3, 30)
            sheet.set_column(4, 4, 12)
            sheet.set_column(5, 5, 30)
            sheet.set_column(6, 6, 12)

            current_row += 1
            quarter_total = 0
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
st.title("💰 雲端記帳本")

df = load_data()

# 頁籤：手動輸入 vs 匯入發票
tab_manual, tab_import = st.tabs(["📝 手動記帳", "☁️ 匯入雲端發票"])

# === 功能一：手動記帳 (欄位已交換) ===
with tab_manual:
    date_input = st.date_input("選擇日期", datetime.now())
    
    # 這裡調整欄位順序與寬度比例：細項(長) | 金額(短)
    col1, col2 = st.columns([2, 1]) 
    
    with col1:
        item_input = st.text_input("購物細項", placeholder="例如：午餐")
        
    with col2:
        # 改成 text_input 以支援算式
        amount_str = st.text_input("金額 (可輸入算式)", placeholder="如: 100+50", value="")

    if st.button("新增記錄", use_container_width=True):
        # 1. 計算金額
        final_amount = safe_calculate(amount_str)
        
        if item_input and final_amount is not None and final_amount > 0:
            new_data = pd.DataFrame({
                '日期': [date_input],
                '購物細項': [item_input],
                '金額': [int(final_amount)] # 轉成整數存檔
            })
            df = pd.concat([df, new_data], ignore_index=True)
            save_data(df)
            st.success(f"已儲存：{item_input} ${int(final_amount)}")
            st.rerun()
        elif final_amount is None:
            st.error("金額格式錯誤！請輸入數字或簡單算式 (如 100+50)")
        else:
            st.error("請輸入完整的項目名稱與金額！")

# === 功能二：匯入雲端發票 (維持不變) ===
with tab_import:
    st.markdown("### 批次匯入發票 CSV")
    uploaded_file = st.file_uploader("選擇 CSV 檔案", type=['csv'])
    if uploaded_file is not None:
        try:
            try: import_df = pd.read_csv(uploaded_file, encoding='utf-8')
            except: import_df = pd.read_csv(uploaded_file, encoding='cp950')
            
            st.dataframe(import_df.head(3))
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
                    df = pd.concat([df, new_df], ignore_index=True)
                    save_data(df)
                    st.success(f"成功匯入 {len(new_records)} 筆！")
                    st.rerun()
        except Exception as e: st.error(f"錯誤：{e}")

# --- 5. 數據統計與顯示 (新版：今日/本周/本月) ---
st.markdown("---")
st.subheader("📊 帳務總覽")

if not df.empty:
    # 準備日期變數
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday()) # 週一為開始
    start_of_month = today.replace(day=1)

    # 建立分頁
    tab1, tab2, tab3 = st.tabs(["📅 今日總計", "🗓️ 本周總計", "📊 本月總計"])
    
    # 定義一個共用的顯示函數 (避免程式碼重複)
    def display_filtered_records(filtered_df, tab_name):
        if filtered_df.empty:
            st.info(f"{tab_name} 目前沒有消費記錄。")
        else:
            total_amount = filtered_df['金額'].sum()
            st.metric(label=f"{tab_name} 總支出", value=f"${total_amount:,}")
            
            st.write("📋 **詳細清單**")
            # 為了要能刪除，我們必須保留原始 index
            # sort_values 後 reset_index 會產生一個叫 'index' 的欄位保留原始索引
            display_df = filtered_df.sort_values('日期', ascending=False).reset_index()

            # 標題
            h1, h2, h3, h4 = st.columns([2.5, 3.5, 2, 2])
            h1.write("**日期**"); h2.write("**項目**"); h3.write("**金額**"); h4.write("**操作**")

            # 列表
            for i, row in display_df.iterrows():
                c1, c2, c3, c4 = st.columns([2.5, 3.5, 2, 2])
                c1.write(f"{row['日期']}")
                c2.write(f"{row['購物細項']}")
                c3.write(f"${row['金額']}")
                
                # 每個按鈕需要唯一的 key，我們用 tab 名稱 + 原始 index
                unique_key = f"del_{tab_name}_{row['index']}"
                if c4.button("刪除", key=unique_key, type="secondary"):
                    # 使用全域變數 df 和 save_data
                    global df 
                    df = df.drop(row['index']) # 刪除原始資料
                    save_data(df)
                    st.warning(f"已刪除：{row['購物細項']}")
                    st.rerun()

    # --- 分頁 1: 今日 ---
    with tab1:
        df_today = df[df['日期'] == today]
        display_filtered_records(df_today, "今日")

    # --- 分頁 2: 本周 ---
    with tab2:
        # 篩選 >= 週一 且 <= 今天 (或是未來也可以，這邊抓 >= start_of_week)
        df_week = df[df['日期'] >= start_of_week]
        display_filtered_records(df_week, "本周")

    # --- 分頁 3: 本月 ---
    with tab3:
        # 篩選同一年且同一月
        df['dt_temp'] = pd.to_datetime(df['日期'])
        df_month = df[(df['dt_temp'].dt.year == today.year) & (df['dt_temp'].dt.month == today.month)]
        display_filtered_records(df_month, "本月")

    st.markdown("---")
    # 匯出按鈕
    excel_data = generate_custom_excel(df)
    if excel_data:
        st.download_button("下載年度清冊 (.xlsx)", excel_data.getvalue(), f'年度支出_{datetime.now().strftime("%Y%m%d")}.xlsx', "application/vnd.ms-excel")

else:
    st.info("目前還沒有資料。")