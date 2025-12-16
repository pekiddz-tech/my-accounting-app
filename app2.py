import streamlit as st
import pandas as pd
from datetime import datetime
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 設定頁面
st.set_page_config(page_title="雲端記帳 App", layout="centered")

# --- 設定區 (請修改這裡) ---
# 你的 Google Sheet 網址
SHEET_URL = "https://docs.google.com/spreadsheets/d/1MdOuH0QUDQko6rzZxf94d2SK3dHsnQKav_luJLCJhEo/edit?usp=sharing"

# --- 1. 連線 Google Sheets 函數 ---
def connect_to_sheet():
    # 這裡使用 Streamlit 的 secrets 功能來管理金鑰，安全又方便
    # 確保你的 .streamlit/secrets.toml 已經設定好
    try:
        # 定義權限範圍
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        
        # 從 secrets 讀取憑證
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SHEET_URL).sheet1
        return sheet
    except Exception as e:
        st.error(f"連線失敗，請檢查 secrets 設定或是試算表權限: {e}")
        return None

def load_data():
    sheet = connect_to_sheet()
    if sheet:
        try:
            # 讀取所有記錄
            data = sheet.get_all_records()
            df = pd.DataFrame(data)
            
            # 如果是空的 DataFrame (剛建立時)
            if df.empty:
                return pd.DataFrame(columns=['日期', '購物細項', '金額'])
            
            # 確保日期格式正確
            # Google Sheet 讀下來可能是字串，需轉換
            df['日期'] = pd.to_datetime(df['日期']).dt.date
            return df
        except Exception:
            # 如果發生讀取錯誤(例如格式不對)，回傳空的
            return pd.DataFrame(columns=['日期', '購物細項', '金額'])
    return pd.DataFrame(columns=['日期', '購物細項', '金額'])

def save_data(df):
    sheet = connect_to_sheet()
    if sheet:
        # Google Sheets 不支援直接寫入 datetime 物件，要轉成字串
        df_to_save = df.copy()
        df_to_save['日期'] = df_to_save['日期'].astype(str)
        
        # 更新策略：為了資料安全，我們先讀取表頭，然後把內容全部覆蓋
        # 這是最簡單防止資料錯亂的方式
        sheet.clear() # 清空
        # 寫入欄位名稱 (Header)
        # gspread update 比較快的方式是把 list of lists 寫進去
        sheet.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())

# --- 2. 核心功能：Excel 匯出 (維持不變) ---
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

# --- 3. App 介面 ---
st.title("💰 DRKKY雲端記帳本 (Google Sheets 版)")

# 載入資料 (這會稍微久一點點，因為要連網路)
df = load_data()

tab_manual, tab_import = st.tabs(["📝 手動記帳", "☁️ 匯入雲端發票"])

with tab_manual:
    col1, col2 = st.columns(2)
    with col1: date_input = st.date_input("選擇日期", datetime.now())
    with col2: amount_input = st.number_input("金額 ($)", min_value=0, step=1)
    item_input = st.text_input("購物細項")

    if st.button("新增記錄", use_container_width=True):
        if item_input and amount_input > 0:
            new_data = pd.DataFrame({'日期': [date_input], '購物細項': [item_input], '金額': [amount_input]})
            df = pd.concat([df, new_data], ignore_index=True)
            save_data(df)
            st.success(f"已儲存至 Google Sheets：{item_input}")
            st.rerun()
        else:
            st.error("請輸入完整資料")

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
            with c1: col_date = st.selectbox("日期欄位", all_columns, index=0)
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
                    save_data(df) # 寫入 Google Sheets
                    st.success(f"成功匯入 {len(new_records)} 筆！")
                    st.rerun()
        except Exception as e: st.error(f"錯誤：{e}")

st.markdown("---")
st.subheader("📊 帳務管理")

if not df.empty:
    st.write("🗑️ **最近 10 筆記錄**")
    display_df = df.sort_values('日期', ascending=False).tail(10).sort_values('日期', ascending=False).reset_index()
    h1, h2, h3, h4 = st.columns([2.5, 3.5, 2, 2])
    h1.write("**日期**"); h2.write("**項目**"); h3.write("**金額**"); h4.write("**操作**")

    for i, row in display_df.iterrows():
        c1, c2, c3, c4 = st.columns([2.5, 3.5, 2, 2])
        c1.write(f"{row['日期']}")
        c2.write(f"{row['購物細項']}")
        c3.write(f"${row['金額']}")
        unique_key = f"del_{row['index']}"
        if c4.button("刪除", key=unique_key, type="secondary"):
            df = df.drop(row['index'])
            save_data(df) # 同步刪除雲端
            st.warning("已刪除")
            st.rerun()
            
    st.markdown("---")
    excel_data = generate_custom_excel(df)
    if excel_data:
        st.download_button("下載年度清冊 (.xlsx)", excel_data.getvalue(), f'年度支出_{datetime.now().strftime("%Y%m%d")}.xlsx', "application/vnd.ms-excel")