"""
大成高鑫股票A (000628) 增强版独立估值系统
功能: 实时估值 + 基金经理跟踪 + 基金规模监测
特点: 多数据源冗余 | 历史数据追踪 | 实时监控报警
"""

import pandas as pd
import akshare as ak
import requests
import json
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import sys
import os
from dataclasses import dataclass
import matplotlib.pyplot as plt
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fund_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ManagerChange:
    """基金经理变更记录"""
    change_date: str
    manager_name: str
    start_date: str
    end_date: Optional[str] = None
    tenure_days: int = 0

@dataclass
class FundSizeRecord:
    """基金规模记录"""
    record_date: str
    total_size: float  # 亿元
    shares_outstanding: float  # 亿份
    nav: float

class FundManagerTracker:
    """基金经理变更跟踪系统"""
    
    def __init__(self):
        self.manager_history: List[ManagerChange] = []
        self.current_manager = None
        self.load_manager_history()
    
    def load_manager_history(self):
        """加载基金经理历史数据（实际应从基金公告获取）"""
        # 模拟数据 - 实际应从基金公告提取
        history_data = [
            ManagerChange("2023-08-15", "张燕", "2023-08-15", "2024-05-20", 279),
            ManagerChange("2024-05-21", "刘旭", "2024-05-21", "2025-12-15", 574),
            ManagerChange("2025-12-16", "王明", "2025-12-16", None, 46),  # 现任，截至2026-01-31
        ]
        
        self.manager_history = history_data
        self.current_manager = history_data[-1] if history_data else None
        
        logger.info(f"加载基金经理历史记录: {len(history_data)}次变更")
    
    def get_current_manager_info(self, current_date: str = None) -> Dict:
        """获取当前基金经理信息"""
        if not self.current_manager:
            return {"error": "未找到基金经理信息"}
        
        if current_date is None:
            current_date = datetime.now().strftime('%Y%m%d')
        
        # 计算任职天数
        start_date = datetime.strptime(self.current_manager.start_date, "%Y-%m-%d")
        end_date = datetime.now()
        
        return {
            "name": self.current_manager.manager_name,
            "start_date": self.current_manager.start_date,
            "tenure_days": (end_date - start_date).days,
            "current_date": current_date,
            "status": "在任"
        }
    
    def add_manager_change(self, change_date: str, manager_name: str):
        """添加基金经理变更记录"""
        new_change = ManagerChange(
            change_date=change_date,
            manager_name=manager_name,
            start_date=change_date
        )
        
        # 更新上一条记录的结束日期
        if self.manager_history:
            self.manager_history[-1].end_date = change_date
            end_date = datetime.strptime(change_date, "%Y-%m-%d")
            start_date = datetime.strptime(self.manager_history[-1].start_date, "%Y-%m-%d")
            self.manager_history[-1].tenure_days = (end_date - start_date).days
        
        self.manager_history.append(new_change)
        self.current_manager = new_change
        logger.info(f"添加基金经理变更: {change_date} -> {manager_name}")
    
    def get_manager_history_report(self) -> str:
        """生成基金经理变更报告"""
        report = "基金经理变更历史:\n"
        report += "=" * 50 + "\n"
        report += f"{'变更日期':<12} {'基金经理':<8} {'任职天数':<8} {'状态':<6}\n"
        report += "-" * 50 + "\n"
        
        for record in self.manager_history:
            status = "在任" if record.end_date is None else "离任"
            tenure = record.tenure_days if record.tenure_days > 0 else "现任"
            end_date = record.end_date if record.end_date else "至今"
            
            report += f"{record.change_date:<12} {record.manager_name:<8} "
            report += f"{tenure if isinstance(tenure, str) else str(tenure)+'天':<8} {status:<6}\n"
        
        return report

class FundSizeMonitor:
    """基金规模变化监测系统"""
    
    def __init__(self, fund_code: str = "000628"):
        self.fund_code = fund_code
        self.size_history: List[FundSizeRecord] = []
        self.load_size_history()
    
    def load_size_history(self):
        """加载基金规模历史数据（模拟数据，实际应从季报获取）"""
        # 模拟数据 - 实际应从基金季报提取
        history_data = [
            FundSizeRecord("2024-03-31", 85.42, 18.23, 4.682),
            FundSizeRecord("2024-06-30", 92.15, 19.15, 4.812),
            FundSizeRecord("2024-09-30", 98.76, 20.12, 4.908),
            FundSizeRecord("2024-12-31", 105.32, 21.08, 4.995),
            FundSizeRecord("2025-03-31", 112.45, 22.15, 5.076),
            FundSizeRecord("2025-06-30", 118.23, 23.01, 5.138),
            FundSizeRecord("2025-09-30", 120.42, 23.45, 5.135),
            FundSizeRecord("2025-12-31", 122.18, 23.68, 5.159),
        ]
        
        self.size_history = history_data
        logger.info(f"加载基金规模历史记录: {len(history_data)}个季度")
    
    def add_size_record(self, record_date: str, total_size: float, nav: float):
        """添加基金规模记录"""
        shares_outstanding = total_size / nav if nav > 0 else 0
        
        new_record = FundSizeRecord(
            record_date=record_date,
            total_size=total_size,
            shares_outstanding=shares_outstanding,
            nav=nav
        )
        
        self.size_history.append(new_record)
        self.size_history.sort(key=lambda x: x.record_date)
        logger.info(f"添加基金规模记录: {record_date} - {total_size}亿元")
    
    def get_size_trend_analysis(self) -> Dict:
        """分析基金规模趋势"""
        if len(self.size_history) < 2:
            return {"error": "历史数据不足"}
        
        latest = self.size_history[-1]
        previous = self.size_history[-2]
        
        # 计算季度变化
        size_change = latest.total_size - previous.total_size
        size_change_pct = (size_change / previous.total_size) * 100
        
        # 计算年化增长率
        if len(self.size_history) >= 5:
            oldest = self.size_history[0]
            years = (datetime.strptime(latest.record_date, "%Y-%m-%d") - 
                    datetime.strptime(oldest.record_date, "%Y-%m-%d")).days / 365
            if years > 0:
                cagr = ((latest.total_size / oldest.total_size) ** (1/years) - 1) * 100
            else:
                cagr = 0
        else:
            cagr = None
        
        return {
            "current_size": latest.total_size,
            "current_nav": latest.nav,
            "current_shares": latest.shares_outstanding,
            "quarterly_change": round(size_change, 2),
            "quarterly_change_pct": round(size_change_pct, 2),
            "annual_growth_rate": round(cagr, 2) if cagr else None,
            "record_date": latest.record_date,
            "quarters_count": len(self.size_history)
        }
    
    def get_size_history_chart_data(self) -> Dict:
        """获取规模变化图表数据"""
        dates = [record.record_date for record in self.size_history]
        sizes = [record.total_size for record in self.size_history]
        navs = [record.nav for record in self.size_history]
        
        return {
            "dates": dates,
            "sizes": sizes,
            "navs": navs
        }
    
    def save_size_chart(self, filename: str = "fund_size_trend.png"):
        """生成并保存基金规模趋势图"""
        try:
            chart_data = self.get_size_history_chart_data()
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
            
            # 规模趋势图
            ax1.plot(chart_data["dates"], chart_data["sizes"], 'b-o', linewidth=2, markersize=6)
            ax1.set_title(f'大成高鑫股票A({self.fund_code}) 基金规模趋势', fontsize=14, fontweight='bold')
            ax1.set_ylabel('规模 (亿元)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.tick_params(axis='x', rotation=45)
            
            # 净值趋势图
            ax2.plot(chart_data["dates"], chart_data["navs"], 'g-s', linewidth=2, markersize=6)
            ax2.set_title('单位净值趋势', fontsize=14, fontweight='bold')
            ax2.set_xlabel('季度', fontsize=12)
            ax2.set_ylabel('净值 (元)', fontsize=12)
            ax2.grid(True, alpha=0.3)
            ax2.tick_params(axis='x', rotation=45)
            
            plt.tight_layout()
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            
            logger.info(f"规模趋势图已保存: {filename}")
            return filename
        except Exception as e:
            logger.error(f"生成趋势图失败: {e}")
            return None

class EnhancedFundValuationSystem:
    """增强版基金估值系统（集成基金经理跟踪和规模监测）"""
    
    def __init__(self, fund_code: str = '000628', base_nav: float = 5.3312):
        """
        初始化增强版估值系统
        
        Args:
            fund_code: 基金代码
            base_nav: 基准净值
        """
        self.fund_code = fund_code
        self.fund_name = "大成高鑫股票A"
        self.base_nav = base_nav
        
        # 初始化三大模块
        self.valuation_core = self._init_valuation_core()
        self.manager_tracker = FundManagerTracker()
        self.size_monitor = FundSizeMonitor(fund_code)
        
        # 价格缓存
        self.price_cache = {}
        self.cache_ttl = 60
        
        logger.info(f"增强版估值系统初始化完成: {self.fund_name}({self.fund_code})")
    
    def _init_valuation_core(self):
        """初始化估值核心参数"""
        self.cash_ratio = 0.1654  # 现金比例 16.54%
        self.stock_ratio = 0.8346  # 股票比例 83.46%
        self.fund_size = 120.42e8  # 基金规模约120.42亿元
        self.total_shares = self.fund_size / self.base_nav
        
        # 持仓数据（示例，需要更新为真实数据）
        self.portfolio = self._load_portfolio_data()
        
        return {
            "fund_size": self.fund_size,
            "total_shares": self.total_shares,
            "portfolio_size": len(self.portfolio)
        }
    
    def _load_portfolio_data(self) -> Dict:
        """加载持仓数据"""
        portfolio_data = {
            '00941': {'shares': 20493500, 'weight': 0.0951, 'name': '中国移动'},
            '000333': {'shares': 21674600, 'weight': 0.0947, 'name': '美的集团'},
            '002595': {'shares': 22135100, 'weight': 0.0722, 'name': '豪迈科技'},
            '600660': {'shares': 14402000, 'weight': 0.0450, 'name': '福耀玻璃'},
            '600741': {'shares': 32091000, 'weight': 0.0400, 'name': '华域汽车'},
            '000858': {'shares': 8512300, 'weight': 0.0380, 'name': '五粮液'},
            # ... 其他持仓（实际应使用完整持仓）
        }
        return portfolio_data
    
    def _get_cached_price(self, stock_code: str) -> Optional[float]:
        """获取缓存价格"""
        if stock_code in self.price_cache:
            price, timestamp = self.price_cache[stock_code]
            if time.time() - timestamp < self.cache_ttl:
                return price
        return None
    
    def _set_cached_price(self, stock_code: str, price: float):
        """设置缓存价格"""
        self.price_cache[stock_code] = (price, time.time())
    
    def get_stock_price(self, stock_code: str) -> Optional[float]:
        """获取股票价格（简化版）"""
        cached_price = self._get_cached_price(stock_code)
        if cached_price is not None:
            return cached_price
        
        try:
            if stock_code.startswith(('6', '0', '3')):  # A股
                market = 'sh' if stock_code.startswith('6') else 'sz'
                url = f"http://qt.gtimg.cn/q={market}{stock_code}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(url, headers=headers, timeout=5)
                response.encoding = 'gbk'
                data = response.text.split('~')
                if len(data) > 3 and data[3]:
                    price = float(data[3])
                    self._set_cached_price(stock_code, price)
                    return price
        except Exception as e:
            logger.warning(f"获取股票价格失败 {stock_code}: {e}")
        
        return None
    
    def calculate_real_time_valuation(self) -> Dict:
        """计算实时估值"""
        logger.info("开始计算实时估值...")
        
        total_stock_value = 0.0
        valid_stocks = 0
        failed_stocks = []
        
        print(f"\n📊 正在计算 {self.fund_name}({self.fund_code}) 实时估值")
        print(f"持仓股票数: {len(self.portfolio)}")
        print("=" * 60)
        
        # 计算股票持仓价值
        for i, (stock_code, info) in enumerate(self.portfolio.items(), 1):
            if i % 10 == 0:
                print(f"进度: {i}/{len(self.portfolio)} | 有效: {valid_stocks} | 失败: {len(failed_stocks)}")
            
            price = self.get_stock_price(stock_code)
            if price is not None:
                stock_value = info['shares'] * price
                total_stock_value += stock_value
                valid_stocks += 1
            else:
                failed_stocks.append(stock_code)
            
            time.sleep(0.05)
        
        # 计算净值
        if total_stock_value > 0:
            known_weight_sum = sum(info.get('weight', 0) for info in self.portfolio.values())
            
            if known_weight_sum > 0.3:
                estimated_total_assets = total_stock_value / known_weight_sum
            else:
                estimated_total_assets = total_stock_value / self.stock_ratio
            
            estimated_nav = estimated_total_assets / self.total_shares
            change_pct = ((estimated_nav - self.base_nav) / self.base_nav) * 100
            
            # 获取基金经理和规模信息
            manager_info = self.manager_tracker.get_current_manager_info("20260131")
            size_analysis = self.size_monitor.get_size_trend_analysis()
            
            result = {
                'fund_code': self.fund_code,
                'fund_name': self.fund_name,
                'base_nav': self.base_nav,
                'estimated_nav': round(estimated_nav, 4),
                'change_pct': round(change_pct, 2),
                'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'valid_stocks': valid_stocks,
                'total_stocks': len(self.portfolio),
                'manager_info': manager_info,
                'size_analysis': size_analysis,
                'fund_size': self.fund_size,
                'success_rate': round(valid_stocks / len(self.portfolio) * 100, 1)
            }
            
            return result
        else:
            return {"error": "估值计算失败"}
    
    def generate_comprehensive_report(self) -> str:
        """生成综合报告"""
        # 获取估值结果
        valuation = self.calculate_real_time_valuation()
        
        # 获取基金经理历史
        manager_report = self.manager_tracker.get_manager_history_report()
        
        # 获取规模分析
        size_analysis = self.size_monitor.get_size_trend_analysis()
        
        # 生成报告
        report = "\n" + "=" * 70
        report += f"\n📋 {self.fund_name}({self.fund_code}) 综合监测报告"
        report += f"\n" + "=" * 70
        
        # 估值部分
        if 'error' not in valuation:
            report += f"\n📈 实时估值信息:"
            report += f"\n   更新时间: {valuation['update_time']}"
            report += f"\n   基准净值: {valuation['base_nav']:.4f}"
            report += f"\n   估算净值: {valuation['estimated_nav']:.4f}"
            
            change = valuation['change_pct']
            if change > 0:
                report += f"\n   估算涨跌: +{change:.2f}% 📈"
            else:
                report += f"\n   估算涨跌: {change:.2f}% 📉"
            
            report += f"\n   数据质量: {valuation['valid_stocks']}/{valuation['total_stocks']} 只股票 ({valuation['success_rate']}%)"
        else:
            report += f"\n❌ 估值计算失败: {valuation['error']}"
        
        # 基金经理部分
        report += f"\n\n👨‍💼 基金经理信息:"
        manager_info = valuation.get('manager_info', {})
        if 'error' not in manager_info:
            report += f"\n   现任经理: {manager_info.get('name', '未知')}"
            report += f"\n   任职日期: {manager_info.get('start_date', '未知')}"
            report += f"\n   任职天数: {manager_info.get('tenure_days', '未知')}天"
            report += f"\n   当前状态: {manager_info.get('status', '未知')}"
        else:
            report += f"\n   经理信息: {manager_info.get('error', '获取失败')}"
        
        # 规模分析部分
        report += f"\n\n💰 基金规模分析:"
        size_info = valuation.get('size_analysis', {})
        if 'error' not in size_info:
            report += f"\n   当前规模: {size_info.get('current_size', 0):.2f} 亿元"
            report += f"\n   最新净值: {size_info.get('current_nav', 0):.4f}"
            report += f"\n   最新份额: {size_info.get('current_shares', 0):.2f} 亿份"
            
            q_change = size_info.get('quarterly_change_pct', 0)
            if q_change > 0:
                report += f"\n   季度变化: +{q_change:.2f}% 📈"
            else:
                report += f"\n   季度变化: {q_change:.2f}% 📉"
            
            annual_rate = size_info.get('annual_growth_rate')
            if annual_rate:
                report += f"\n   年化增长: {annual_rate:.2f}%"
        else:
            report += f"\n   规模信息: {size_info.get('error', '获取失败')}"
        
        report += f"\n\n" + "=" * 70
        report += f"\n📊 历史数据摘要:"
        report += f"\n" + "-" * 70
        
        # 添加基金经理历史摘要
        report += f"\n{manager_report}"
        
        report += f"\n" + "=" * 70
        report += f"\n💡 系统说明:"
        report += f"\n   1. 估值基于持仓 + 实时股价独立计算"
        report += f"\n   2. 基金经理数据为模拟数据，实际请从公告获取"
        report += f"\n   3. 规模数据基于季报，当前为模拟数据"
        report += f"\n   4. 实际净值以基金公司公布为准"
        report += f"\n" + "=" * 70
        
        return report
    
    def monitor_alert(self, threshold_pct: float = 5.0) -> List[str]:
        """监控报警系统"""
        alerts = []
        
        # 1. 估值大幅波动报警
        valuation = self.calculate_real_time_valuation()
        if 'error' not in valuation:
            change_pct = abs(valuation['change_pct'])
            if change_pct > threshold_pct:
                alerts.append(f"⚠️ 估值大幅波动: {valuation['change_pct']:.2f}% (阈值: {threshold_pct}%)")
        
        # 2. 规模异常报警
        size_analysis = self.size_monitor.get_size_trend_analysis()
        if 'error' not in size_analysis:
            q_change = size_analysis.get('quarterly_change_pct', 0)
            if abs(q_change) > 20:  # 季度规模变化超过20%
                alerts.append(f"⚠️ 规模异常变化: {q_change:.2f}%")
        
        # 3. 数据质量报警
        if 'error' not in valuation and valuation['success_rate'] < 80:
            alerts.append(f"⚠️ 数据质量较低: {valuation['success_rate']:.1f}% 股票获取成功")
        
        return alerts
    
    def save_comprehensive_data(self):
        """保存综合数据"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 1. 保存文本报告
        report = self.generate_comprehensive_report()
        report_file = f"fund_report_{self.fund_code}_{timestamp}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        # 2. 保存JSON数据
        valuation = self.calculate_real_time_valuation()
        json_file = f"fund_data_{self.fund_code}_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(valuation, f, ensure_ascii=False, indent=2)
        
        # 3. 生成趋势图
        chart_file = self.size_monitor.save_size_chart(f"fund_trend_{self.fund_code}_{timestamp}.png")
        
        logger.info(f"综合数据已保存: {report_file}, {json_file}, {chart_file}")
        return {
            "report_file": report_file,
            "data_file": json_file,
            "chart_file": chart_file
        }
    
    def run_continuous_monitoring(self, interval_minutes: int = 30, alert_threshold: float = 5.0):
        """持续监控模式"""
        print(f"\n🔔 启动增强版持续监控，每{interval_minutes}分钟更新一次...")
        print("按 Ctrl+C 停止监控")
        
        monitor_count = 0
        try:
            while True:
                monitor_count += 1
                print(f"\n{'='*70}")
                print(f"🔄 第{monitor_count}次综合监测")
                print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # 生成报告
                report = self.generate_comprehensive_report()
                print(report)
                
                # 检查报警
                alerts = self.monitor_alert(alert_threshold)
                if alerts:
                    print(f"\n🚨 系统报警:")
                    for alert in alerts:
                        print(f"   {alert}")
                
                # 保存数据（每3次保存一次）
                if monitor_count % 3 == 0:
                    self.save_comprehensive_data()
                
                # 等待下次更新
                if monitor_count == 1:
                    print(f"\n📊 下次完整报告将在 {interval_minutes} 分钟后生成...")
                else:
                    print(f"\n⏳ 等待下次更新...")
                
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            print("\n\n👋 监控已停止")
        except Exception as e:
            logger.error(f"监控异常: {e}")

def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("大成高鑫股票A (000628) 增强版监控系统")
    print("功能: 实时估值 + 基金经理跟踪 + 基金规模监测")
    print("=" * 70)
    
    # 创建增强版系统
    print("\n正在初始化增强版监控系统...")
    system = EnhancedFundValuationSystem(
        fund_code='000628',
        base_nav=5.3312
    )
    
    # 显示系统信息
    print(f"基金名称: {system.fund_name}")
    print(f"基金代码: {system.fund_code}")
    print(f"持仓股票: {system.valuation_core['portfolio_size']}只")
    print(f"基金经理: {system.manager_tracker.current_manager.manager_name if system.manager_tracker.current_manager else '未知'}")
    print(f"基金规模: {system.fund_size/1e8:.2f}亿元")
    
    # 选择模式
    print("\n" + "=" * 70)
    print("请选择运行模式:")
    print("1. 生成单次综合报告")
    print("2. 启动持续监控")
    print("3. 查看基金经理历史")
    print("4. 查看规模趋势图")
    print("5. 保存所有数据")
    print("=" * 70)
    
    choice = input("\n请输入选项 (1-5): ").strip()
    
    if choice == '1':
        # 生成综合报告
        print("\n正在生成综合报告...")
        report = system.generate_comprehensive_report()
        print(report)
        
        # 保存报告
        save_choice = input("\n是否保存报告? (y/N): ").strip().lower()
        if save_choice == 'y':
            system.save_comprehensive_data()
    
    elif choice == '2':
        # 持续监控
        interval = input("请输入更新间隔（分钟，默认30）: ").strip()
        interval_min = int(interval) if interval.isdigit() else 30
        
        threshold = input("请输入报警阈值（%，默认5）: ").strip()
        threshold_val = float(threshold) if threshold.replace('.', '').isdigit() else 5.0
        
        system.run_continuous_monitoring(interval_min, threshold_val)
    
    elif choice == '3':
        # 查看基金经理历史
        report = system.manager_tracker.get_manager_history_report()
        print(report)
        
        # 显示当前经理信息
        current = system.manager_tracker.get_current_manager_info()
        if 'error' not in current:
            print(f"\n📅 当前基金经理信息:")
            print(f"   姓名: {current['name']}")
            print(f"   任职日期: {current['start_date']}")
            print(f"   任职天数: {current['tenure_days']}天")
            print(f"   状态: {current['status']}")
    
    elif choice == '4':
        # 查看规模趋势图
        print("\n正在生成规模趋势图...")
        chart_file = system.size_monitor.save_size_chart()
        if chart_file:
            print(f"趋势图已生成: {chart_file}")
            print("请查看当前目录下的PNG文件")
        
        # 显示规模分析
        analysis = system.size_monitor.get_size_trend_analysis()
        if 'error' not in analysis:
            print(f"\n📊 规模趋势分析:")
            print(f"   当前规模: {analysis['current_size']:.2f}亿元")
            print(f"   最新净值: {analysis['current_nav']:.4f}")
            print(f"   季度变化: {analysis['quarterly_change_pct']:+.2f}%")
            if analysis['annual_growth_rate']:
                print(f"   年化增长: {analysis['annual_growth_rate']:+.2f}%")
    
    elif choice == '5':
        # 保存所有数据
        print("\n正在保存所有数据...")
        files = system.save_comprehensive_data()
        print(f"\n✅ 数据保存完成:")
        print(f"   报告文件: {files['report_file']}")
        print(f"   数据文件: {files['data_file']}")
        print(f"   趋势图: {files['chart_file']}")
    
    else:
        print("无效选项，程序退出")

if __name__ == "__main__":
    # 检查依赖
    try:
        import akshare
        import pandas
        import requests
        import matplotlib
        print("✅ 所有依赖库已就绪")
    except ImportError as e:
        print(f"❌ 缺少依赖库: {e}")
        print("请运行: pip install akshare pandas requests matplotlib")
        sys.exit(1)
    
    # 运行主程序
    main()