import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, simpledialog
import pandas as pd
import numpy as np
import os
import datetime
import sys
import requests
import threading

# ==========================================
# ⚙️ 基础配置
# ==========================================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

FILE_PATH = os.path.join(base_dir, "账本.xlsx")


# ==========================================
# 🧠 核心逻辑 Manager
# ==========================================
class ExcelManager:
    def __init__(self, filepath):
        self.filepath = filepath

    def check_file(self):
        try:
            with open(self.filepath, "a"):
                pass
            return True, ""
        except PermissionError:
            return False, "❌ Excel 正被占用，请关闭它！"
        except FileNotFoundError:
            return False, "❌ 找不到 账本.xlsx"

    def read_data(self):
        try:
            dfs = pd.read_excel(self.filepath, sheet_name=None)
            trans = dfs.get('流水', pd.DataFrame()).copy()
            assets = dfs.get('总资产管理', pd.DataFrame()).copy()
            config = dfs.get('配置表', pd.DataFrame()).copy()
            for df in [trans, assets, config]:
                if not df.empty: df.columns = df.columns.str.strip()
            return trans, assets, config
        except Exception as e:
            return None, None, None

    def force_sync(self):
        ok, msg = self.check_file()
        if not ok: return False, msg
        trans, assets, config = self.read_data()
        if trans is None: return False, "读取失败"
        return self.recalculate_and_save(trans, assets, config)

    def update_account_balance(self, account_name, new_total_balance):
        ok, msg = self.check_file()
        if not ok: return False, msg
        trans, assets, config = self.read_data()
        flow_sum = 0.0
        if not trans.empty:
            def get_sign(row):
                try:
                    amt = float(row['金额'])
                except:
                    return 0
                if row['类型'] in ['支出', '转出']:
                    return -1 * amt
                elif row['类型'] in ['收入', '转入', '余额调整']:
                    return 1 * amt
                return 0

            acc_trans = trans[trans['账户'] == account_name].copy()
            if not acc_trans.empty:
                acc_trans['变动'] = acc_trans.apply(get_sign, axis=1)
                flow_sum = acc_trans['变动'].sum()
        new_initial = float(new_total_balance) - flow_sum
        if assets.empty: assets = pd.DataFrame(columns=['账户', '期初余额'])
        if account_name in assets['账户'].values:
            assets.loc[assets['账户'] == account_name, '期初余额'] = new_initial
        else:
            curr = 'CNY'
            if not trans.empty:
                last = trans[trans['账户'] == account_name]
                if not last.empty: curr = last.iloc[-1]['币种']
            new_row = pd.DataFrame([{'账户': account_name, '币种': curr, '期初余额': new_initial}])
            assets = pd.concat([assets, new_row], ignore_index=True)
        return self.recalculate_and_save(trans, assets, config)

    def get_all_currencies(self):
        if not os.path.exists(self.filepath): return ["CNY", "HKD", "USD"]
        trans, assets, config = self.read_data()
        curr_set = {"CNY", "HKD", "USD"}
        if trans is not None and '币种' in trans.columns:
            curr_set.update(trans['币种'].dropna().astype(str).unique())
        if assets is not None and '币种' in assets.columns:
            curr_set.update(assets['币种'].dropna().astype(str).unique())
        if config is not None and '币种' in config.columns:
            curr_set.update(config['币种'].dropna().astype(str).unique())
        return sorted(list(curr_set))

    def get_accounts(self):
        if not os.path.exists(self.filepath): return ["支付宝", "微信"]
        _, assets, _ = self.read_data()
        if assets is not None and '账户' in assets.columns:
            accs = assets['账户'].dropna().unique().tolist()
            return accs if accs else ["支付宝"]
        return ["支付宝"]

    def get_rates(self):
        default_rates = {'CNY': 1.0, 'HKD': 0.89, 'USD': 7.25, 'MOP': 0.87}
        if not os.path.exists(self.filepath): return default_rates
        _, _, config = self.read_data()
        if config is not None and not config.empty:
            try:
                rates = dict(zip(config['币种'].astype(str), config['换汇汇率']))
                rates['CNY'] = 1.0
                return rates
            except:
                pass
        return default_rates

    def get_current_total(self):
        if not os.path.exists(self.filepath): return 0.0
        _, assets, _ = self.read_data()
        if assets is not None and not assets.empty and '总资产(CNY)' in assets.columns:
            val = assets['总资产(CNY)'].iloc[0]
            if pd.notnull(val): return float(val)
        return 0.0

    def get_asset_details(self):
        if not os.path.exists(self.filepath): return []
        _, assets, _ = self.read_data()
        if assets is None or assets.empty: return []
        result = []
        for _, row in assets.iterrows():
            if pd.notnull(row['账户']):
                bal = row['当前余额'] if '当前余额' in row else 0
                cny_val = row['折合人民币'] if '折合人民币' in row else 0
                curr = str(row['币种']) if pd.notnull(row['币种']) else "CNY"
                result.append({
                    'account': str(row['账户']),
                    'currency': curr,
                    'balance': float(bal) if pd.notnull(bal) else 0,
                    'cny_val': float(cny_val) if pd.notnull(cny_val) else 0
                })
        result.sort(key=lambda x: x['cny_val'], reverse=True)
        return result

    def get_recent_transactions_with_index(self, limit=30):
        if not os.path.exists(self.filepath): return []
        trans, _, _ = self.read_data()
        if trans is None or trans.empty: return []
        try:
            trans['日期'] = pd.to_datetime(trans['日期'])
        except:
            return []
        df_sorted = trans.sort_values(by='日期', ascending=False).reset_index().head(limit)
        result = []
        for _, row in df_sorted.iterrows():
            result.append({
                'id': row['index'],
                'date': row['日期'].strftime("%Y-%m-%d"),
                'item': row['项目'],
                'amount': row['金额'],
                'currency': row['币种'],
                'type': row['类型']
            })
        return result

    def delete_transaction_by_id(self, original_index):
        ok, msg = self.check_file()
        if not ok: return False, msg
        trans_df, assets_df, config_df = self.read_data()
        if trans_df is None: return False, "读取失败"
        try:
            trans_df = trans_df.drop(original_index)
        except KeyError:
            return False, "找不到该记录"
        return self.recalculate_and_save(trans_df, assets_df, config_df)

    def get_dashboard_stats(self):
        """返回 (日支,日收, 周支,周收, 月支,月收, 流水文本)"""
        zero_res = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "暂无数据")
        if not os.path.exists(self.filepath): return zero_res

        trans, _, config = self.read_data()
        if trans is None or trans.empty: return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "暂无流水")

        try:
            trans['日期'] = pd.to_datetime(trans['日期'])
        except:
            return zero_res

        trans['币种'] = trans['币种'].astype(str)
        if config is not None:
            config['币种'] = config['币种'].astype(str)
            if '换汇汇率' in trans.columns: trans = trans.drop(columns=['换汇汇率'])
            trans = trans.merge(config[['币种', '换汇汇率']], on='币种', how='left')
            trans['换汇汇率'] = trans['换汇汇率'].fillna(1)
        else:
            trans['换汇汇率'] = 1
        trans['折合金额'] = trans['金额'] * trans['换汇汇率']

        now = datetime.datetime.now()
        today_date = now.date()
        start_of_week = today_date - datetime.timedelta(days=now.weekday())

        # === v12.1 修复: 只统计纯【支出】和【收入】，剔除转账 ===
        def calc_stats(df_subset):
            if df_subset.empty: return 0.0, 0.0
            # 只筛选 '支出'，忽略 '转出'
            exp = df_subset[df_subset['类型'] == '支出']['折合金额'].sum()
            # 只筛选 '收入'，忽略 '转入' 和 '余额调整'
            inc = df_subset[df_subset['类型'] == '收入']['折合金额'].sum()
            return exp, inc

        # 1. 日统计
        df_day = trans[trans['日期'].dt.date == today_date]
        d_exp, d_inc = calc_stats(df_day)

        # 2. 周统计
        df_week = trans[trans['日期'].dt.date >= start_of_week]
        w_exp, w_inc = calc_stats(df_week)

        # 3. 月统计 & 流水列表
        df_month = trans[(trans['日期'].dt.year == now.year) & (trans['日期'].dt.month == now.month)].copy()
        m_exp, m_inc = calc_stats(df_month)

        # 生成列表文本 (列表里还是显示所有类型，方便核对)
        df_month_sorted = df_month.sort_values(by='日期', ascending=False)
        lines = []
        for _, row in df_month_sorted.iterrows():
            d_str = row['日期'].strftime("%m-%d")
            is_exp = row['类型'] in ['支出', '转出']
            sign = "-" if is_exp else "+"
            # 转账记录可以在列表里加个标记，或者保持原样
            line = f"{d_str} | {row['项目']} | {sign}{row['金额']} {row['币种']}"
            lines.append(line)

        log_text = "\n".join(lines) if lines else "本月暂无流水"

        return d_exp, d_inc, w_exp, w_inc, m_exp, m_inc, log_text

    def update_rates(self, new_rates_dict):
        ok, msg = self.check_file()
        if not ok: return False, msg
        trans, assets, _ = self.read_data()
        new_config_data = []
        for curr, rate in new_rates_dict.items():
            new_config_data.append({'币种': curr, '换汇汇率': float(rate), '备注': '手动更新'})
        new_config_df = pd.DataFrame(new_config_data)
        return self.save_all(trans, assets, new_config_df)

    def save_transaction(self, date, item, amount, account, trans_type, currency):
        ok, msg = self.check_file()
        if not ok: return False, msg
        trans_df, assets_df, config_df = self.read_data()
        if trans_df is None: return False, "读取 Excel 失败"
        new_row = {'日期': date, '项目': item, '账户': account, '币种': currency, '金额': float(amount),
                   '类型': trans_type}
        trans_df = pd.concat([trans_df, pd.DataFrame([new_row])], ignore_index=True)
        return self.recalculate_and_save(trans_df, assets_df, config_df)

    def recalculate_and_save(self, trans_df, assets_df, config_df):
        # 这里的计算逻辑不能变！因为算余额时，转账必须算进去！
        if assets_df.empty:
            assets_df = pd.DataFrame(columns=['账户', '币种', '期初余额'])
        if '期初余额' not in assets_df.columns:
            if '金额' in assets_df.columns:
                assets_df.rename(columns={'金额': '期初余额'}, inplace=True)
            else:
                assets_df['期初余额'] = 0.0
        trans_df['币种'] = trans_df['币种'].astype(str)
        config_df['币种'] = config_df['币种'].astype(str)
        all_currs = trans_df['币种'].unique()
        exist_conf = config_df['币种'].unique()
        for c in set(all_currs) - set(exist_conf):
            config_df = pd.concat([config_df, pd.DataFrame([{'币种': c, '换汇汇率': 1.0}])], ignore_index=True)
        if '换汇汇率' in trans_df.columns: trans_df = trans_df.drop(columns=['换汇汇率'])
        trans_df = trans_df.merge(config_df[['币种', '换汇汇率']], on='币种', how='left')
        trans_df['换汇汇率'] = trans_df['换汇汇率'].fillna(1)

        # 余额计算逻辑（保持原样，包含转账）
        def get_sign(row):
            try:
                amt = float(row['金额'])
            except:
                return 0
            if row['类型'] in ['支出', '转出']:
                return -1 * amt
            elif row['类型'] in ['收入', '转入', '余额调整']:
                return 1 * amt
            return 0

        trans_df['实际变动'] = trans_df.apply(get_sign, axis=1)
        trans_df['折合人民币'] = trans_df['金额'] * trans_df['换汇汇率']
        summary = trans_df.groupby('账户')['实际变动'].sum().reset_index()
        summary.rename(columns={'实际变动': '流水变动'}, inplace=True)
        asset_map = {}
        for _, row in assets_df.iterrows():
            if pd.notnull(row['账户']):
                asset_map[str(row['账户'])] = {
                    'currency': row['币种'] if pd.notnull(row['币种']) else 'CNY',
                    'initial': row['期初余额'] if pd.notnull(row['期初余额']) else 0.0
                }
        all_accs = set(asset_map.keys()) | set(trans_df['账户'].dropna())
        for acc in all_accs:
            if acc not in asset_map:
                curr = 'CNY'
                last = trans_df[trans_df['账户'] == acc]
                if not last.empty: curr = last.iloc[-1]['币种']
                asset_map[acc] = {'currency': curr, 'initial': 0.0}
        new_assets_data = []
        for acc, info in asset_map.items():
            new_assets_data.append({'账户': acc, '币种': info['currency'], '期初余额': info['initial']})
        assets_df = pd.DataFrame(new_assets_data)
        assets_df = assets_df.merge(summary, on='账户', how='left')
        assets_df['流水变动'] = assets_df['流水变动'].fillna(0)
        assets_df['当前余额'] = assets_df['期初余额'] + assets_df['流水变动']
        assets_df = assets_df.merge(config_df[['币种', '换汇汇率']], on='币种', how='left')
        assets_df['换汇汇率'] = assets_df['换汇汇率'].fillna(1)
        assets_df['折合人民币'] = assets_df['当前余额'] * assets_df['换汇汇率']
        grand_total = assets_df['折合人民币'].sum()
        assets_df['总资产(CNY)'] = np.nan
        assets_df.loc[0, '总资产(CNY)'] = grand_total
        return self.save_all(trans_df, assets_df, config_df, grand_total)

    def save_all(self, trans, assets, config, total_val=None):
        try:
            with pd.ExcelWriter(self.filepath, mode='w') as writer:
                cols_t = ['日期', '项目', '账户', '币种', '金额', '类型', '换汇汇率', '折合人民币', '实际变动']
                for c in cols_t:
                    if c not in trans.columns: trans[c] = np.nan
                trans[cols_t].to_excel(writer, sheet_name='流水', index=False)
                cols_a = ['账户', '币种', '期初余额', '流水变动', '当前余额', '换汇汇率', '折合人民币', '总资产(CNY)']
                assets[cols_a].to_excel(writer, sheet_name='总资产管理', index=False)
                config.to_excel(writer, sheet_name='配置表', index=False)
            if total_val is None:
                if '总资产(CNY)' in assets.columns:
                    total_val = assets['总资产(CNY)'].iloc[0]
                else:
                    total_val = 0
            return True, f"¥ {total_val:,.2f}"
        except Exception as e:
            return False, str(e)


# ==========================================
# 🎨 窗口类
# ==========================================
class AccountOverviewWindow(ctk.CTkToplevel):
    def __init__(self, parent, excel_mgr):
        super().__init__(parent)
        self.title("账户透视中心")
        self.geometry("500x600")
        self.excel_mgr = excel_mgr
        self.parent = parent
        ctk.CTkLabel(self, text="点击 ✎ 可修改校准余额", text_color="gray").pack(pady=10)
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=15, pady=5)
        self.load_data()

    def load_data(self):
        for w in self.scroll.winfo_children(): w.destroy()
        lst = self.excel_mgr.get_asset_details()
        if not lst: ctk.CTkLabel(self.scroll, text="无数据").pack(pady=20); return
        for acc in lst:
            card = ctk.CTkFrame(self.scroll)
            card.pack(fill="x", pady=5, padx=5)
            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=10, pady=10)
            ctk.CTkLabel(left, text=acc['account'], font=("bold", 14)).pack(anchor="w")
            ctk.CTkLabel(left, text=f"{acc['balance']:,.2f} {acc['currency']}", text_color="gray").pack(anchor="w")
            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=10)
            ctk.CTkButton(right, text="✎", width=30, height=30, fg_color="#3498DB",
                          command=lambda a=acc['account'], c=acc['currency']: self.edit_balance(a, c)).pack(
                side="right", padx=(10, 0))
            info_frame = ctk.CTkFrame(right, fg_color="transparent")
            info_frame.pack(side="right")
            ctk.CTkLabel(info_frame, text="≈ 折合(CNY)", font=("", 10), text_color="gray").pack(anchor="e")
            ctk.CTkLabel(info_frame, text=f"¥ {acc['cny_val']:,.2f}", text_color="#2CC985", font=("bold", 14)).pack(
                anchor="e")

    def edit_balance(self, account, curr):
        dialog = ctk.CTkInputDialog(text=f"请输入【{account}】的实际余额 ({curr}):", title="资产校准")
        new_val_str = dialog.get_input()
        if new_val_str:
            try:
                new_val = float(new_val_str)
                ok, msg = self.excel_mgr.update_account_balance(account, new_val)
                if ok:
                    messagebox.showinfo("成功", f"已将 {account} 余额校准为 {new_val}")
                    self.load_data();
                    self.parent.refresh_ui()
                else:
                    messagebox.showerror("失败", msg)
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字！")


class TransactionManagerWindow(ctk.CTkToplevel):
    def __init__(self, parent, excel_mgr):
        super().__init__(parent)
        self.title("流水管理")
        self.geometry("500x600")
        self.excel_mgr = excel_mgr
        self.parent = parent
        ctk.CTkLabel(self, text="最近 30 条流水", text_color="gray").pack(pady=10)
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=15, pady=5)
        self.load_data()

    def load_data(self):
        for w in self.scroll.winfo_children(): w.destroy()
        lst = self.excel_mgr.get_recent_transactions_with_index()
        if not lst: ctk.CTkLabel(self.scroll, text="无数据").pack(pady=20); return
        for t in lst:
            row = ctk.CTkFrame(self.scroll)
            row.pack(fill="x", pady=5)
            is_exp = t['type'] in ['支出', '转出']
            col = "#FF4D4D" if is_exp else "#2CC985"
            ctk.CTkLabel(row, text=f"{t['date']} {t['item']}", font=("", 12)).pack(side="left", padx=10)
            ctk.CTkLabel(row, text=f"{'-' if is_exp else '+'}{t['amount']} {t['currency']}", text_color=col,
                         font=("bold", 12)).pack(side="left")
            ctk.CTkButton(row, text="删除", width=60, fg_color="#FF4D4D",
                          command=lambda i=t['id']: self.delete(i)).pack(side="right", padx=10, pady=5)

    def delete(self, idx):
        if messagebox.askyesno("确认", "删除此记录？"):
            ok, msg = self.excel_mgr.delete_transaction_by_id(idx)
            if ok:
                self.load_data(); self.parent.refresh_ui(); messagebox.showinfo("成功", "已删除")
            else:
                messagebox.showerror("错误", msg)


class RateConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent, excel_mgr):
        super().__init__(parent)
        self.title("汇率配置")
        self.geometry("300x500")
        self.excel_mgr = excel_mgr
        self.parent = parent
        self.entries = {}
        self.curr_rates = excel_mgr.get_rates()
        self.all_currs = excel_mgr.get_all_currencies()
        ctk.CTkLabel(self, text="修改汇率 (对CNY)", font=("bold", 16)).pack(pady=10)
        ctk.CTkButton(self, text="☁️ 联网更新实时汇率", fg_color="#8E44AD", hover_color="#9B59B6",
                      command=self.start_fetch_rates).pack(pady=5)
        self.status_lbl = ctk.CTkLabel(self, text="", font=("", 10))
        self.status_lbl.pack()
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)
        for c in self.all_currs:
            if c == 'CNY': continue
            row = ctk.CTkFrame(self.scroll, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(row, text=c, width=40).pack(side="left")
            e = ctk.CTkEntry(row, width=120)
            e.insert(0, str(self.curr_rates.get(c, 1.0)))
            e.pack(side="right")
            self.entries[c] = e
        ctk.CTkButton(self, text="保存并应用", command=self.save).pack(pady=20)

    def start_fetch_rates(self):
        self.status_lbl.configure(text="正在连接国际汇率接口...", text_color="blue")
        threading.Thread(target=self.fetch_online_rates, daemon=True).start()

    def fetch_online_rates(self):
        try:
            url = "https://api.exchangerate-api.com/v4/latest/CNY"
            response = requests.get(url, timeout=5)
            data = response.json()
            rates = data.get('rates', {})
            updated_count = 0
            for curr, entry in self.entries.items():
                if curr in rates and rates[curr] > 0:
                    my_rate = 1.0 / rates[curr]
                    entry.delete(0, 'end')
                    entry.insert(0, f"{my_rate:.4f}")
                    updated_count += 1
            self.status_lbl.configure(text=f"✅ 成功更新 {updated_count} 个币种", text_color="green")
        except Exception as e:
            self.status_lbl.configure(text=f"❌ 更新失败: 网络错误", text_color="red")

    def save(self):
        new_r = {}
        for c, e in self.entries.items():
            v = e.get().strip()
            if v:
                try:
                    new_r[c] = float(v)
                except:
                    pass
        ok, msg = self.excel_mgr.update_rates(new_r)
        if ok:
            self.parent.refresh_ui(); self.destroy(); messagebox.showinfo("成功", "已更新")
        else:
            messagebox.showerror("错误", msg)


# ==========================================
# 🎨 主界面
# ==========================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.excel_mgr = ExcelManager(FILE_PATH)
        self.title("MoneyApp v12.1 PureStats")
        self.geometry("480x880")
        self.resizable(False, False)
        self.main_font = ("Microsoft YaHei UI", 14)

        self.excel_mgr.force_sync()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(15, 0))
        ctk.CTkLabel(top, text="我的资产", font=("bold", 20)).pack(side="left")

        btn_box = ctk.CTkFrame(top, fg_color="transparent")
        btn_box.pack(side="right")
        ctk.CTkButton(btn_box, text="🔄 刷新", width=60, command=self.sync_data).pack(side="right", padx=2)
        ctk.CTkButton(btn_box, text="💳 账户", width=60, command=self.open_accounts).pack(side="right", padx=2)
        ctk.CTkButton(btn_box, text="⚙️ 汇率", width=60, command=self.open_config).pack(side="right", padx=2)
        ctk.CTkButton(btn_box, text="🗑️ 管理", width=60, fg_color="#E74C3C", command=self.open_manager).pack(
            side="right", padx=2)

        dash = ctk.CTkFrame(self, fg_color="transparent")
        dash.pack(pady=10)
        ctk.CTkLabel(dash, text="总折合人民币 (CNY)", text_color="gray").pack()
        self.total_lbl = ctk.CTkLabel(dash, text="¥ 0.00", font=("bold", 40), text_color="#2CC985")
        self.total_lbl.pack()
        self.rate_lbl = ctk.CTkLabel(self, text="...", text_color="gray")
        self.rate_lbl.pack(pady=(0, 10))

        self.frame = ctk.CTkFrame(self)
        self.frame.pack(padx=20, fill="both")
        self.frame.columnconfigure(1, weight=1)

        self.inputs = {}
        self.build_input(0, "📅 日期", "date")
        self.build_input(1, "📝 项目", "item")
        self.build_input(2, "💰 金额", "amount")
        self.build_input(3, "💳 账户", "account")
        self.build_input(4, "🗂️ 类型", "type", ["支出", "收入", "转出", "转入"])
        self.build_input(5, "💱 币种", "curr", ["CNY"])

        self.save_btn = ctk.CTkButton(self, text="💾 立即入账", height=45, font=("bold", 14), command=self.submit)
        self.save_btn.pack(pady=15, padx=20, fill="x")
        self.status = ctk.CTkLabel(self, text="就绪", text_color="gray")
        self.status.pack()

        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.pack(fill="x", padx=25, pady=5)

        ctk.CTkLabel(stats_frame, text="📅 今日", text_color="gray").grid(row=0, column=0, padx=5, sticky="w")
        ctk.CTkLabel(stats_frame, text="📅 本周", text_color="gray").grid(row=1, column=0, padx=5, sticky="w")
        ctk.CTkLabel(stats_frame, text="📅 本月", text_color="gray").grid(row=2, column=0, padx=5, sticky="w")

        self.d_exp_lbl = ctk.CTkLabel(stats_frame, text="支 0", text_color="#FF4D4D")
        self.d_inc_lbl = ctk.CTkLabel(stats_frame, text="收 0", text_color="#2CC985")
        self.d_exp_lbl.grid(row=0, column=1, padx=10);
        self.d_inc_lbl.grid(row=0, column=2, padx=10)

        self.w_exp_lbl = ctk.CTkLabel(stats_frame, text="支 0", text_color="#FF4D4D")
        self.w_inc_lbl = ctk.CTkLabel(stats_frame, text="收 0", text_color="#2CC985")
        self.w_exp_lbl.grid(row=1, column=1, padx=10);
        self.w_inc_lbl.grid(row=1, column=2, padx=10)

        self.m_exp_lbl = ctk.CTkLabel(stats_frame, text="支 0", text_color="#FF4D4D")
        self.m_inc_lbl = ctk.CTkLabel(stats_frame, text="收 0", text_color="#2CC985")
        self.m_exp_lbl.grid(row=2, column=1, padx=10);
        self.m_inc_lbl.grid(row=2, column=2, padx=10)

        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(2, weight=1)

        self.log = ctk.CTkTextbox(self, height=130)
        self.log.pack(padx=20, pady=10, fill="both", expand=True)

        self.refresh_ui()

    def build_input(self, r, txt, tag, vals=None):
        ctk.CTkLabel(self.frame, text=txt, font=self.main_font).grid(row=r, column=0, padx=15, pady=8, sticky="w")
        if tag == "date":
            w = ctk.CTkEntry(self.frame, font=self.main_font)
            w.insert(0, datetime.date.today().strftime("%Y-%m-%d"))
        elif tag == "item" or tag == "amount":
            w = ctk.CTkEntry(self.frame, font=self.main_font)
        else:
            w = ctk.CTkComboBox(self.frame, values=vals or [], font=self.main_font)
        w.grid(row=r, column=1, padx=10, pady=8, sticky="ew")
        self.inputs[tag] = w

    def sync_data(self):
        self.save_btn.configure(text="⏳ 同步中...", state="disabled")
        self.update()
        ok, msg = self.excel_mgr.force_sync()
        if ok:
            self.refresh_ui()
            messagebox.showinfo("同步成功", "已读取Excel最新数据并重新计算！")
        else:
            messagebox.showerror("同步失败", msg)
        self.save_btn.configure(text="💾 立即入账", state="normal")

    def refresh_ui(self):
        self.inputs['account'].configure(values=self.excel_mgr.get_accounts())
        self.inputs['curr'].configure(values=self.excel_mgr.get_all_currencies())
        self.total_lbl.configure(text=f"¥ {self.excel_mgr.get_current_total():,.2f}")
        rates = self.excel_mgr.get_rates()
        rt = " | ".join([f"{k}:{v}" for k, v in rates.items() if k in ['HKD', 'USD', 'MOP']])
        self.rate_lbl.configure(text=rt)

        d_exp, d_inc, w_exp, w_inc, m_exp, m_inc, txt = self.excel_mgr.get_dashboard_stats()

        self.d_exp_lbl.configure(text=f"支出: ¥{d_exp:,.0f}")
        self.d_inc_lbl.configure(text=f"收入: ¥{d_inc:,.0f}")
        self.w_exp_lbl.configure(text=f"支出: ¥{w_exp:,.0f}")
        self.w_inc_lbl.configure(text=f"收入: ¥{w_inc:,.0f}")
        self.m_exp_lbl.configure(text=f"支出: ¥{m_exp:,.2f}")
        self.m_inc_lbl.configure(text=f"收入: ¥{m_inc:,.2f}")

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", txt)
        self.log.configure(state="disabled")

    def submit(self):
        d = self.inputs['date'].get()
        i = self.inputs['item'].get()
        a = self.inputs['amount'].get()
        acc = self.inputs['account'].get()
        t = self.inputs['type'].get()
        c = self.inputs['curr'].get()
        if not i or not a: self.status.configure(text="❌ 缺信息", text_color="red"); return
        try:
            float(a)
        except:
            self.status.configure(text="❌ 金额非数字", text_color="red"); return
        self.save_btn.configure(state="disabled", text="⏳...")
        self.update()
        ok, msg = self.excel_mgr.save_transaction(d, i, a, acc, t, c)
        if ok:
            self.status.configure(text="✅ 成功", text_color="green")
            self.inputs['item'].delete(0, "end")
            self.inputs['amount'].delete(0, "end")
            self.refresh_ui()
        else:
            messagebox.showerror("错", msg)
        self.save_btn.configure(state="normal", text="💾 立即入账")

    def open_config(self):
        RateConfigWindow(self, self.excel_mgr)

    def open_accounts(self):
        AccountOverviewWindow(self, self.excel_mgr)

    def open_manager(self):
        TransactionManagerWindow(self, self.excel_mgr)


if __name__ == "__main__":
    app = App()
    app.mainloop()


    