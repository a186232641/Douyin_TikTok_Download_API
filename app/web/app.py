# PyWebIO组件/PyWebIO components
import os
import time

import yaml
from pywebio import session, config as pywebio_config
from pywebio.input import *
from pywebio.output import *

from app.web.views.About import about_pop_window
from app.web.views.Document import api_document_pop_window
from app.web.views.DouyinCookie import douyin_cookie_pop_window
from app.web.views.Downloader import downloader_pop_window
from app.web.views.EasterEgg import a
from app.web.views.ParseVideo import parse_video
from app.web.views.Shortcuts import ios_pop_window
# PyWebIO的各个视图/Views of PyWebIO
from app.web.views.ViewsUtils import ViewsUtils
from app.runtime_config import is_access_password_configured, verify_access_password

# 读取上级再上级目录的配置文件
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as file:
    _config = yaml.safe_load(file)

pywebio_config(theme=_config['Web']['PyWebIO_Theme'],
               title=_config['Web']['Tab_Title'],
               description=_config['Web']['Description'],
               js_file=[
                   # 整一个看板娘，二次元浓度++
                   _config['Web']['Live2D_JS'] if _config['Web']['Live2D_Enable'] else None,
               ])


class MainView:
    def __init__(self):
        self.utils = ViewsUtils()

    # 主界面/Main view
    def main_view(self):
        if not self._authenticate():
            return

        # 左侧导航栏/Left navbar
        with use_scope('main'):
            # 设置favicon/Set favicon
            favicon_url = _config['Web']['Favicon']
            session.run_js(f"""
                            $('head').append('<link rel="icon" type="image/png" href="{favicon_url}">')
                            """)
            # 修改footer/Remove footer
            session.run_js("""$('footer').remove()""")
            # 设置不允许referrer/Set no referrer
            session.run_js("""$('head').append('<meta name=referrer content=no-referrer>');""")
            # 设置标题/Set title
            title = self.utils.t("TikTok/抖音无水印在线解析下载",
                                 "Douyin/TikTok online parsing and download without watermark")
            put_html(f"""
                    <div align="center">
                    <a href="/" alt="logo" ><img src="{favicon_url}" width="100"/></a>
                    <h1 align="center">{title}</h1>
                    </div>
                    """)
            # 设置导航栏/Navbar
            put_row(
                [
                    put_button(self.utils.t("快捷指令", 'iOS Shortcut'),
                               onclick=lambda: ios_pop_window(), link_style=True, small=True),
                    put_button(self.utils.t("开放接口", 'Open API'),
                               onclick=lambda: api_document_pop_window(), link_style=True, small=True),
                    put_button(self.utils.t("下载器", "Downloader"),
                               onclick=lambda: downloader_pop_window(), link_style=True, small=True),
                    put_button(self.utils.t("Cookie配置", "Cookie Settings"),
                               onclick=lambda: douyin_cookie_pop_window(), link_style=True, small=True),
                    put_button(self.utils.t("关于", 'About'),
                               onclick=lambda: about_pop_window(), link_style=True, small=True),
                ])

            # 设置功能选择/Function selection
            options = [
                # Index: 0
                self.utils.t('🔍批量解析视频', '🔍Batch Parse Video'),
                # Index: 1
                self.utils.t('🔍解析用户主页视频', '🔍Parse User Homepage Video'),
                # Index: 2
                self.utils.t('🥚小彩蛋', '🥚Easter Egg'),
            ]
            select_options = select(
                self.utils.t('请在这里选择一个你想要的功能吧 ~', 'Please select a function you want here ~'),
                required=True,
                options=options,
                help_text=self.utils.t('📎选上面的选项然后点击提交', '📎Select the options above and click Submit')
            )
            # 根据输入运行不同的函数
            if select_options == options[0]:
                parse_video()
            elif select_options == options[1]:
                put_markdown(self.utils.t('暂未开放，敬请期待~', 'Not yet open, please look forward to it~'))
            elif select_options == options[2]:
                a() if _config['Web']['Easter_Egg'] else put_markdown(self.utils.t('没有小彩蛋哦~', 'No Easter Egg~'))

    def _authenticate(self):
        if not is_access_password_configured():
            put_error(self.utils.t(
                "网页访问密码未配置。请设置 WEB_ACCESS_PASSWORD 环境变量或 config.yaml 中的 Web.Access_Password。",
                "Web access password is not configured. Set WEB_ACCESS_PASSWORD or Web.Access_Password in config.yaml.",
            ))
            return False

        while True:
            password = input(
                self.utils.t("访问密码", "Access password"),
                type=PASSWORD,
                required=True,
            )
            if verify_access_password(password):
                return True
            toast(self.utils.t("密码错误", "Invalid password"), color="error")
            time.sleep(1)
