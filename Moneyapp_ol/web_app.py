import streamlit as st
import pandas as pd
import datetime
import requests
import plotly.express as px
import os

# ==========================================
# ⚙️ 页面配置 (必须在第一行)
# ==========================================
st.set_page_config(
    page_title="MoneyApp v12.1",
    page_icon="💰",
    layout="centered",
    initial_sidebar_state="expanded"
)


# ==========================================
# 🛠️ 核心逻辑函数
# ==========================================

# 1. 获取汇率 (带缓存，防频繁请求)
@st.cache_data(ttl=3600)  # 1小时更新一次
def get_online_rates():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/CNY"
        res = requests.get(url, timeout=3)
        data = res.json()
        rates = data.get('rates', {})
        # 转换为 1 外币 = ? CNY
        final_rates = {'CNY': 1.0}
        for curr, rate in rates.items():
            if rate > 0:
                final_rates[curr] = 1.0 / rate
        return final_rates
    except:
        return {'CNY': 1.0, 'HKD': 0.89, 'USD': 7.25, 'MOP': 0.87}


# 2. 读取/初始化数据
def load_data():
    file_path = "账本.xlsx"
    if not os.path.exists(file_path):
        # 如果没有账本，创建一个空的
        df = pd.DataFrame(columns=['日期', '项目', '账户', '币种', '金额', '类型'])
        return df
    try:
        # 只读取'流水'表
        df = pd.read_excel(file_path, sheet_name='流水')
        # 清洗数据
        df['日期'] = pd.to_datetime(df['日期']).dt.date
        return df
    except:
        return pd.DataFrame(columns=['日期', '项目', '账户', '币种', '金额', '类型'])


# 3. 计算统计数据 (v12.1 逻辑：剔除转账)
def calculate_stats(df, rates):
    if df.empty:
        return 0, 0, 0, 0, 0, 0

    # 统一转换汇率
    df_calc = df.copy()
    df_calc['日期'] = pd.to_datetime(df_calc['日期']).dt.date

    # 映射汇率
    df_calc['汇率'] = df_calc['币种'].map(rates).fillna(1.0)
    df_calc['折合'] = df_calc['金额'] * df_calc['汇率']

    now = datetime.date.today()
    start_week = now - datetime.timedelta(days=now.weekday())  # 本周一
    start_month = datetime.date(now.year, now.month, 1)  # 本月1号

    # 筛选时间段
    mask_day = df_calc['日期'] == now
    mask_week = df_calc['日期'] >= start_week
    mask_month = (pd.to_datetime(df_calc['日期']).dt.year == now.year) & \
                 (pd.to_datetime(df_calc['日期']).dt.month == now.month)

    # 核心计算函数 (只算 支出 和 收入)
    def calc(mask):
        sub = df_calc[mask]
        exp = sub[sub['类型'] == '支出']['折合'].sum()
        inc = sub[sub['类型'] == '收入']['折合'].sum()
        return exp, inc

    d_exp, d_inc = calc(mask_day)
    w_exp, w_inc = calc(mask_week)
    m_exp, m_inc = calc(mask_month)

    return d_exp, d_inc, w_exp, w_inc, m_exp, m_inc


# ==========================================
# 🎨 界面 UI
# ==========================================

st.title("💰 MoneyApp 云端版")
st.caption("v12.1 | 实时汇率 | 智能统计")

# --- 侧边栏：记账区 ---
st.sidebar.header("📝 记一笔")
with st.sidebar.form("entry_form"):
    date_val = st.date_input("日期", datetime.date.today())
    item_val = st.text_input("项目", placeholder="例如：午饭")

    c1, c2 = st.columns(2)
    amount_val = c1.number_input("金额", min_value=0.0, format="%.2f")
    curr_val = c2.selectbox("币种", ["CNY", "HKD", "USD", "MOP"])

    c3, c4 = st.columns(2)
    acc_val = c3.selectbox("账户", ["微信", "支付宝", "余额宝", "银行卡", "现金"])
    type_val = c4.selectbox("类型", ["支出", "收入", "转出", "转入"])

    submitted = st.form_submit_button("💾 立即入账", use_container_width=True)

    if submitted:
        if not item_val or amount_val == 0:
            st.sidebar.error("❌ 请填写项目和金额")
        else:
            # 读取旧数据
            df_old = load_data()
            # 构造新行
            new_row = pd.DataFrame([{
                '日期': date_val,
                '项目': item_val,
                '账户': acc_val,
                '币种': curr_val,
                '金额': amount_val,
                '类型': type_val
            }])
            # 合并并保存
            df_new = pd.concat([df_old, new_row], ignore_index=True)
            # 保存到 Excel (注意：Web版持久化需要特殊处理，这里先保存本地)
            with pd.ExcelWriter("账本.xlsx", mode='w') as writer:
                df_new.to_excel(writer, sheet_name='流水', index=False)
            st.sidebar.success("✅ 入账成功！")
            st.rerun()  # 刷新页面

# --- 主界面：数据展示 ---

# 1. 准备数据
df = load_data()
rates = get_online_rates()

# 2. 三维统计看板
d_e, d_i, w_e, w_i, m_e, m_i = calculate_stats(df, rates)

c1, c2, c3 = st.columns(3)
c1.metric("📅 今日支出", f"¥ {d_e:,.0f}", delta=f"收: {d_i:,.0f}", delta_color="inverse")
c2.metric("📅 本周支出", f"¥ {w_e:,.0f}", delta=f"收: {w_i:,.0f}", delta_color="inverse")
c3.metric("📅 本月支出", f"¥ {m_e:,.2f}", delta=f"收: {m_i:,.2f}", delta_color="inverse")

# 3. 汇率跑马灯
rate_str = " | ".join([f"{k}:{v:.2f}" for k, v in rates.items() if k in ['HKD', 'USD', 'MOP']])
st.info(f"☁️ 实时汇率参考: {rate_str}")

# 4. 流水明细 (可编辑模式)
st.subheader("📋 流水明细")
tab1, tab2 = st.tabs(["流水列表", "数据分析"])

with tab1:
    # 倒序显示
    df_display = df.sort_values(by='日期', ascending=False)
    st.dataframe(
        df_display,
        use_container_width=True,
        column_config={
            "日期": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "金额": st.column_config.NumberColumn("金额", format="%.2f"),
        }
    )

    # 下载按钮 (解决Web版数据保存问题)
    with open("账本.xlsx", "rb") as file:
        st.download_button(
            label="📥 下载最新 Excel 账本 (备份用)",
            data=file,
            file_name="账本_备份.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

with tab2:
    if not df.empty:
        # 只看支出
        df_exp = df[df['类型'] == '支出'].copy()
        if not df_exp.empty:
            fig = px.pie(df_exp, names='账户', values='金额', title='账户支出占比')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.write("暂无支出数据")
    else:
        st.write("暂无数据")

        