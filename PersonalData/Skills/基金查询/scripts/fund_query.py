import sys
import json
import akshare as ak
from datetime import datetime

def get_fund_info(fund_code: str) -> dict:
    try:
        fund_name_df = ak.fund_name_em()
        fund_info = fund_name_df[fund_name_df['基金代码'] == fund_code]
        if not fund_info.empty:
            row = fund_info.iloc[0]
            return {
                "基金代码": str(row["基金代码"]),
                "基金简称": str(row["基金简称"]),
                "基金类型": str(row["基金类型"]),
            }
        return {"error": "未找到该基金信息"}
    except Exception as e:
        return {"error": f"获取基金信息失败: {str(e)}"}

def get_fund_net_value(fund_code: str) -> dict:
    try:
        fund_data = ak.fund_open_fund_info_em(symbol=fund_code)
        if not fund_data.empty:
            latest_data = fund_data.iloc[-1]
            return {
                "日期": str(latest_data["净值日期"]),
                "单位净值": str(latest_data["单位净值"]),
                "日增长率": str(latest_data["日增长率"]) + "%",
            }
        return {"error": "未获取到基金净值数据"}
    except Exception as e:
        return {"error": f"获取基金净值失败: {str(e)}"}

def get_fund_history_net_value(fund_code: str, days: int = 30) -> dict:
    try:
        fund_data = ak.fund_open_fund_info_em(symbol=fund_code)
        if not fund_data.empty:
            history_data = fund_data.tail(days)
            records = []
            for _, row in history_data.iterrows():
                records.append({
                    "日期": str(row["净值日期"]),
                    "单位净值": str(row["单位净值"]),
                    "日增长率": str(row["日增长率"]) + "%",
                })
            return {"history": records}
        return {"error": "未获取到历史净值数据"}
    except Exception as e:
        return {"error": f"获取历史净值失败: {str(e)}"}

def get_fund_net_value_by_period(fund_code: str, start_date: str, end_date: str, filter_type: str = None, threshold: float = 0) -> dict:
    try:
        fund_data = ak.fund_open_fund_info_em(symbol=fund_code)
        if fund_data.empty:
            return {"error": "未获取到基金净值数据"}
        
        fund_data['净值日期'] = fund_data['净值日期'].astype(str)
        
        filtered_records = []
        for _, row in fund_data.iterrows():
            try:
                net_date = datetime.strptime(str(row['净值日期']), "%Y-%m-%d")
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                
                if start_date_obj <= net_date <= end_date_obj:
                    growth_rate = float(row["日增长率"]) if row["日增长率"] else 0
                    
                    if filter_type:
                        if filter_type == "up" and growth_rate > threshold:
                            filtered_records.append({
                                "日期": str(row["净值日期"]),
                                "单位净值": str(row["单位净值"]),
                                "日增长率": f"{growth_rate}%",
                                "涨跌": "上涨"
                            })
                        elif filter_type == "down" and growth_rate < -threshold:
                            filtered_records.append({
                                "日期": str(row["净值日期"]),
                                "单位净值": str(row["单位净值"]),
                                "日增长率": f"{growth_rate}%",
                                "涨跌": "下跌"
                            })
                        elif filter_type == "up_down" and abs(growth_rate) > threshold:
                            filtered_records.append({
                                "日期": str(row["净值日期"]),
                                "单位净值": str(row["单位净值"]),
                                "日增长率": f"{growth_rate}%",
                                "涨跌": "上涨" if growth_rate > 0 else "下跌"
                            })
                    else:
                        filtered_records.append({
                            "日期": str(row["净值日期"]),
                            "单位净值": str(row["单位净值"]),
                            "日增长率": f"{growth_rate}%",
                            "涨跌": "上涨" if growth_rate > 0 else ("下跌" if growth_rate < 0 else "持平")
                        })
            except ValueError:
                continue
        
        if not filtered_records:
            return {"error": f"在{start_date}至{end_date}期间未找到符合条件的净值数据"}
        
        if len(filtered_records) >= 2:
            first_net = float(filtered_records[0]["单位净值"])
            last_net = float(filtered_records[-1]["单位净值"])
            total_growth = ((last_net - first_net) / first_net) * 100
        else:
            total_growth = None
        
        return {
            "基金代码": fund_code,
            "时间段": f"{start_date} 至 {end_date}",
            "记录数": len(filtered_records),
            "期间总涨幅": f"{total_growth:.2f}%" if total_growth is not None else "无法计算",
            "filter_type": filter_type if filter_type else "全部",
            "threshold": threshold if filter_type else 0,
            "data": filtered_records
        }
    except Exception as e:
        return {"error": f"查询净值失败: {str(e)}"}

def get_fund_list_by_date(start_date: str, end_date: str) -> dict:
    try:
        fund_df = ak.fund_new_found_em()
        if fund_df.empty:
            return {"error": "未获取到新成立基金数据"}
        
        fund_df['成立日期'] = fund_df['成立日期'].astype(str)
        
        filtered_funds = []
        for _, row in fund_df.iterrows():
            fund_date = row['成立日期']
            try:
                fund_date_obj = datetime.strptime(fund_date, "%Y-%m-%d")
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                
                if start_date_obj <= fund_date_obj <= end_date_obj:
                    filtered_funds.append({
                        "基金代码": str(row["基金代码"]),
                        "基金简称": str(row["基金简称"]),
                        "发行公司": str(row["发行公司"]),
                        "基金类型": str(row["基金类型"]),
                        "成立日期": str(row["成立日期"]),
                        "募集份额": str(row["募集份额"]),
                        "基金经理": str(row["基金经理"]),
                        "申购状态": str(row["申购状态"]),
                    })
            except ValueError:
                continue
        
        if not filtered_funds:
            return {"error": f"在{start_date}至{end_date}期间未找到新成立的基金"}
        
        return {"funds": filtered_funds, "count": len(filtered_funds)}
    except Exception as e:
        return {"error": f"查询基金列表失败: {str(e)}"}

def get_fund_list_with_growth(start_date: str, end_date: str, filter_type: str = None, threshold: float = 0, limit: int = 50) -> dict:
    try:
        fund_name_df = ak.fund_name_em()
        if fund_name_df.empty:
            return {"error": "未获取到基金列表数据"}
        
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        
        fund_results = []
        processed_count = 0
        
        for _, row in fund_name_df.iterrows():
            if processed_count >= limit:
                break
            
            fund_code = str(row["基金代码"])
            fund_name = str(row["基金简称"])
            fund_type = str(row["基金类型"])
            
            try:
                fund_data = ak.fund_open_fund_info_em(symbol=fund_code)
                if fund_data.empty:
                    continue
                
                fund_data['净值日期'] = fund_data['净值日期'].astype(str)
                
                period_records = []
                for _, data_row in fund_data.iterrows():
                    try:
                        net_date = datetime.strptime(str(data_row['净值日期']), "%Y-%m-%d")
                        if start_date_obj <= net_date <= end_date_obj:
                            period_records.append({
                                "date": net_date,
                                "net_value": float(data_row["单位净值"]) if data_row["单位净值"] else 0,
                                "growth_rate": float(data_row["日增长率"]) if data_row["日增长率"] else 0
                            })
                    except ValueError:
                        continue
                
                if len(period_records) < 2:
                    continue
                
                period_records.sort(key=lambda x: x["date"])
                first_net = period_records[0]["net_value"]
                last_net = period_records[-1]["net_value"]
                total_growth = ((last_net - first_net) / first_net) * 100
                
                up_days = sum(1 for r in period_records if r["growth_rate"] > 0)
                down_days = sum(1 for r in period_records if r["growth_rate"] < 0)
                flat_days = sum(1 for r in period_records if r["growth_rate"] == 0)
                
                max_up = max(r["growth_rate"] for r in period_records)
                max_down = min(r["growth_rate"] for r in period_records)
                
                if filter_type:
                    if filter_type == "up" and total_growth <= threshold:
                        continue
                    elif filter_type == "down" and total_growth >= -threshold:
                        continue
                    elif filter_type == "up_down" and abs(total_growth) <= threshold:
                        continue
                
                fund_results.append({
                    "基金代码": fund_code,
                    "基金简称": fund_name,
                    "基金类型": fund_type,
                    "时间段": f"{start_date} 至 {end_date}",
                    "期间总涨幅": f"{total_growth:.2f}%",
                    "上涨天数": up_days,
                    "下跌天数": down_days,
                    "持平天数": flat_days,
                    "最大涨幅": f"{max_up:.2f}%",
                    "最大跌幅": f"{max_down:.2f}%",
                    "记录数": len(period_records)
                })
                
                processed_count += 1
            except Exception:
                continue
        
        fund_results.sort(key=lambda x: abs(float(x["期间总涨幅"].replace("%", ""))), reverse=True)
        
        if not fund_results:
            return {"error": f"在{start_date}至{end_date}期间未找到符合条件的基金"}
        
        return {
            "funds": fund_results,
            "count": len(fund_results),
            "时间段": f"{start_date} 至 {end_date}",
            "filter_type": filter_type if filter_type else "全部",
            "threshold": threshold if filter_type else 0
        }
    except Exception as e:
        return {"error": f"查询基金净值变化失败: {str(e)}"}

def query_fund(fund_code: str = None, query_type: str = "info", start_date: str = None, end_date: str = None, filter_type: str = None, threshold: float = 0, limit: int = 50) -> dict:
    try:
        if query_type == "list":
            if not start_date or not end_date:
                return {"error": "查询基金列表需要提供起始日期和结束日期"}
            
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
                datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                return {"error": "日期格式错误，应为YYYY-MM-DD格式"}
            
            return get_fund_list_by_date(start_date, end_date)
        
        if query_type == "list_growth":
            if not start_date or not end_date:
                return {"error": "查询基金净值变化需要提供起始日期和结束日期"}
            
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
                datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                return {"error": "日期格式错误，应为YYYY-MM-DD格式"}
            
            if filter_type and filter_type not in ["up", "down", "up_down"]:
                return {"error": "filter_type必须为 up, down, 或 up_down"}
            
            return get_fund_list_with_growth(start_date, end_date, filter_type, threshold, limit)
        
        if query_type == "period":
            if not fund_code:
                return {"error": "基金代码不能为空"}
            
            fund_code = str(fund_code).strip()
            
            if len(fund_code) != 6:
                return {"error": "基金代码必须为6位数字"}
            
            if not start_date or not end_date:
                return {"error": "查询时间段净值需要提供起始日期和结束日期"}
            
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
                datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                return {"error": "日期格式错误，应为YYYY-MM-DD格式"}
            
            if filter_type and filter_type not in ["up", "down", "up_down"]:
                return {"error": "filter_type必须为 up, down, 或 up_down"}
            
            return get_fund_net_value_by_period(fund_code, start_date, end_date, filter_type, threshold)
        
        if not fund_code:
            return {"error": "基金代码不能为空"}
        
        fund_code = str(fund_code).strip()
        
        if len(fund_code) != 6:
            return {"error": "基金代码必须为6位数字"}
        
        if query_type == "info":
            return get_fund_info(fund_code)
        elif query_type == "net":
            return get_fund_net_value(fund_code)
        elif query_type == "history":
            return get_fund_history_net_value(fund_code)
        else:
            return {"error": f"不支持的查询类型: {query_type}，可选值: info, net, history, list, list_growth, period"}
    except Exception as e:
        return {"error": f"查询失败: {str(e)}"}

if __name__ == "__main__":
    query_type = sys.argv[1] if len(sys.argv) > 1 else "info"
    
    if query_type == "list":
        start_date = sys.argv[2] if len(sys.argv) > 2 else ""
        end_date = sys.argv[3] if len(sys.argv) > 3 else ""
        result = query_fund(query_type=query_type, start_date=start_date, end_date=end_date)
    elif query_type == "list_growth":
        start_date = sys.argv[2] if len(sys.argv) > 2 else ""
        end_date = sys.argv[3] if len(sys.argv) > 3 else ""
        filter_type = sys.argv[4] if len(sys.argv) > 4 else None
        if filter_type == "None":
            filter_type = None
        threshold = float(sys.argv[5]) if len(sys.argv) > 5 else 0
        limit = int(sys.argv[6]) if len(sys.argv) > 6 else 50
        result = query_fund(query_type=query_type, start_date=start_date, end_date=end_date, filter_type=filter_type, threshold=threshold, limit=limit)
    elif query_type == "period":
        fund_code = sys.argv[2] if len(sys.argv) > 2 else ""
        start_date = sys.argv[3] if len(sys.argv) > 3 else ""
        end_date = sys.argv[4] if len(sys.argv) > 4 else ""
        filter_type = sys.argv[5] if len(sys.argv) > 5 else None
        if filter_type == "None":
            filter_type = None
        threshold = float(sys.argv[6]) if len(sys.argv) > 6 else 0
        result = query_fund(fund_code=fund_code, query_type=query_type, start_date=start_date, end_date=end_date, filter_type=filter_type, threshold=threshold)
    else:
        fund_code = sys.argv[2] if len(sys.argv) > 2 else "511280"
        result = query_fund(fund_code, query_type)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))