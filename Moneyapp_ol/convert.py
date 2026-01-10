import pandas as pd

# 1. 读取 Excel 里的“流水”表
# 这里的 '流水' 要和你 Excel 左下角那个 Sheet 名字一模一样
df = pd.read_excel("账本.xlsx", sheet_name="流水")

# 2. 另存为 CSV
# index=False 代表不保存最左边的 0,1,2,3... 索引列
# encoding='utf-8-sig' 是为了防止 Excel 打开乱码的专用编码
df.to_csv("data.csv", index=False, encoding="utf-8-sig")

print("✅ 转换成功！data.csv 已生成！")
