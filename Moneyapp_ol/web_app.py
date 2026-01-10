import streamlit as st
import pandas as pd
from github import Github
from io import StringIO
import datetime

# ==========================================
# 1. 配置区域 (为了安全，建议使用 st.secrets)
# ==========================================
# 在本地运行时，请在 .streamlit/secrets.toml 中配置
# 在 Streamlit Cloud 运行时，在 App Settings -> Secrets 中配置
try:
    # 尝试从 Secrets 读取配置 (推荐)
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_NAME = st.secrets["REPO_NAME"] # 格式例如: "LiangWeilun/MoneyApp"
except:
    # 如果没有配置 Secrets，会报错提示
    st.error("请配置 GITHUB_TOKEN 和 REPO_NAME！")
    st.stop()

# ==========================================
# 2. GitHub 连接函数
# ==========================================
def get_repo():
    g = Github(GITHUB_TOKEN)
    return g.get_repo(REPO_NAME)

# ==========================================
# 3. 侧边栏：用户登录系统
# ==========================================
st.sidebar.title("💰 云端记账本")

if 'user' not in st.session_state:
    st.session_state.user = ""

if not st.session_state.user:
    st.sidebar.markdown("---")
    user_input = st.sidebar.text_input("请输入你的名字 (例如 Allen):")
    if st.sidebar.button("登录 / 开始记账"):
        if user_input.strip():
            st.session_state.user = user_input.strip()
            st.rerun() # 刷新页面
        else:
            st.sidebar.warning("名字不能为空")
    st.stop() # 未登录时，停止加载主界面

# ==========================================
# 4. 主界面逻辑 (只有登录后才会执行到这里)
# ==========================================
current_user = st.session_state.user
file_name = f"data_{current_user}.csv" # 关键：文件名带上用户名

st.sidebar.success(f"当前用户: {current_user}")
if st.sidebar.button("退出登录"):
    st.session_state.user = ""
    st.rerun()

st.title(f"👋 你好，{current_user}")

# --- 读取数据 ---
repo = get_repo()
file_exists = False
existing_sha = None # 用于更新文件时验证

try:
    # 尝试获取 GitHub 上的文件
    file_content = repo.get_contents(file_name)
    csv_data = file_content.decoded_content.decode("utf-8")
    df = pd.read_csv(StringIO(csv_data))
    existing_sha = file_content.sha # 记录文件的唯一标识，更新时需要
    file_exists = True
    st.info("✅ 已加载云端账本")
except:
    # 如果报错，说明文件不存在 (新用户)
    st.warning("🆕 这是一个新账号，保存第一笔账单后将自动创建文件。")
    df = pd.DataFrame(columns=["日期", "项目", "金额", "备注"])
    file_exists = False

# --- 显示现有数据 ---
st.dataframe(df, use_container_width=True)

# --- 记账输入区 ---
st.divider()
st.subheader("📝 新增一笔")

col1, col2 = st.columns(2)
with col1:
    date = st.date_input("日期", datetime.date.today())
    item = st.text_input("项目 (例如: 早餐)")
with col2:
    amount = st.number_input("金额", min_value=0.0, step=0.1, format="%.2f")
    note = st.text_input("备注 (可选)")

if st.button("提交保存", type="primary"):
    if not item or amount == 0:
        st.error("请至少填写项目和金额")
    else:
        # 1. 构造新数据
        new_row = pd.DataFrame({
            "日期": [date],
            "项目": [item],
            "金额": [amount],
            "备注": [note]
        })
        
        # 2. 合并数据
        updated_df = pd.concat([df, new_row], ignore_index=True)
        
        # 3. 转回 CSV 格式
        updated_csv = updated_df.to_csv(index=False)
        
        # 4. 推送到 GitHub
        try:
            if file_exists:
                # 更新现有文件 (必须提供 sha)
                repo.update_file(
                    path=file_name,
                    message=f"Update by {current_user}",
                    content=updated_csv,
                    sha=existing_sha
                )
            else:
                # 创建新文件
                repo.create_file(
                    path=file_name,
                    message=f"Init by {current_user}",
                    content=updated_csv
                )
            st.success("🎉 保存成功！云端已更新。")
            st.rerun() # 刷新页面显示新数据
        except Exception as e:
            st.error(f"保存失败: {e}")
