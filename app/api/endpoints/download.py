import os
import zipfile

import aiofiles
import httpx
import yaml
from fastapi import APIRouter, Request, Query  # 导入FastAPI组件
from starlette.responses import FileResponse

from app.api.models.APIResponseModel import ErrorResponseModel  # 导入响应模型
from crawlers.hybrid.hybrid_crawler import HybridCrawler  # 导入混合数据爬虫

router = APIRouter()
HybridCrawler = HybridCrawler()

# 读取上级再上级目录的配置文件
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as file:
    config = yaml.safe_load(file)


async def fetch_data(url: str, headers: dict = None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    } if headers is None else headers.get('headers')
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()  # 确保响应是成功的
        return response


@router.get("/download", summary="在线下载抖音|TikTok视频/图片/Online download Douyin|TikTok video/image")
async def download_file_hybrid(request: Request,
                               url: str = Query(
                                   example="https://www.douyin.com/video/7372484719365098803",
                                   description="视频或图片的URL地址，也支持抖音|TikTok的分享链接，例如：https://v.douyin.com/e4J8Q7A/"),
                               prefix: bool = True,
                               with_watermark: bool = False):
    """
    # [中文]
    ### 用途:
    - 在线下载抖音|TikTok 无水印或有水印的视频/图片
    - 通过传入的视频URL参数，获取对应的视频或图片数据，然后下载到本地。
    - 如果你在尝试直接访问TikTok单一视频接口的JSON数据中的视频播放地址时遇到HTTP403错误，那么你可以使用此接口来下载视频。
    - 这个接口会占用一定的服务器资源，所以在Demo站点是默认关闭的，你可以在本地部署后调用此接口。
    ### 参数:
    - url: 视频或图片的URL地址，也支持抖音|TikTok的分享链接，例如：https://v.douyin.com/e4J8Q7A/。
    - prefix: 下载文件的前缀，默认为True，可以在配置文件中修改。
    - with_watermark: 是否下载带水印的视频或图片，默认为False。
    ### 返回:
    - 返回下载的视频或图片文件响应。

    # [English]
    ### Purpose:
    - Download Douyin|TikTok video/image with or without watermark online.
    - By passing the video URL parameter, get the corresponding video or image data, and then download it to the local.
    - If you encounter an HTTP403 error when trying to access the video playback address in the JSON data of the TikTok single video interface directly, you can use this interface to download the video.
    - This interface will occupy a certain amount of server resources, so it is disabled by default on the Demo site, you can call this interface after deploying it locally.
    ### Parameters:
    - url: The URL address of the video or image, also supports Douyin|TikTok sharing links, for example: https://v.douyin.com/e4J8Q7A/.
    - prefix: The prefix of the downloaded file, the default is True, and can be modified in the configuration file.
    - with_watermark: Whether to download videos or images with watermarks, the default is False.
    ### Returns:
    - Return the response of the downloaded video or image file.

    # [示例/Example]
    url: https://www.douyin.com/video/7372484719365098803
    """
    # 是否开启此端点/Whether to enable this endpoint
    if not config["API"]["Download_Switch"]:
        code = 400
        message = "Download endpoint is disabled in the configuration file. | 配置文件中已禁用下载端点。"
        return ErrorResponseModel(code=code, message=message, router=request.url.path,
                                  params=dict(request.query_params))

    # 开始解析数据/Start parsing data
    try:
        data = await HybridCrawler.hybrid_parsing_single_video(url, minimal=True)
    except Exception as e:
        code = 400
        return ErrorResponseModel(code=code, message=str(e), router=request.url.path, params=dict(request.query_params))

    # 开始下载文件/Start downloading files
    try:
        data_type = data.get('type')
        platform = data.get('platform')
        aweme_id = data.get('aweme_id')
        file_prefix = config.get("API").get("Download_File_Prefix") if prefix else ''
        download_path = os.path.join(config.get("API").get("Download_Path"), f"{platform}_{data_type}")

        # 确保目录存在/Ensure the directory exists
        os.makedirs(download_path, exist_ok=True)

        # 下载视频文件/Download video file
        if data_type == 'video':
            file_name = f"{file_prefix}{platform}_{aweme_id}.mp4" if not with_watermark else f"{file_prefix}{platform}_{aweme_id}_watermark.mp4"
            url = data.get('video_data').get('nwm_video_url_HQ') if not with_watermark else data.get('video_data').get(
                'wm_video_url_HQ')
            file_path = os.path.join(download_path, file_name)

            # 判断文件是否存在，存在就直接返回
            if os.path.exists(file_path):
                return FileResponse(path=file_path, media_type='video/mp4', filename=file_name)

            # 获取视频文件
            __headers = await HybridCrawler.TikTokWebCrawler.get_tiktok_headers() if platform == 'tiktok' else await HybridCrawler.DouyinWebCrawler.get_douyin_headers()
            response = await fetch_data(url, headers=__headers)

            # 保存文件
            async with aiofiles.open(file_path, 'wb') as out_file:
                await out_file.write(response.content)

            # 返回文件内容
            return FileResponse(path=file_path, filename=file_name, media_type="video/mp4")

        # 下载图片文件/Download image file
        elif data_type == 'image':
            # 压缩文件属性/Compress file properties
            zip_file_name = f"{file_prefix}{platform}_{aweme_id}_images.zip" if not with_watermark else f"{file_prefix}{platform}_{aweme_id}_images_watermark.zip"
            zip_file_path = os.path.join(download_path, zip_file_name)

            # 判断文件是否存在，存在就直接返回、
            if os.path.exists(zip_file_path):
                return FileResponse(path=zip_file_path, filename=zip_file_name, media_type="application/zip")

            # 获取图片文件/Get image file
            urls = data.get('image_data').get('no_watermark_image_list') if not with_watermark else data.get(
                'image_data').get('watermark_image_list')
            image_file_list = []
            for url in urls:
                # 请求图片文件/Request image file
                response = await fetch_data(url)
                index = int(urls.index(url))
                content_type = response.headers.get('content-type')
                file_format = content_type.split('/')[1]
                file_name = f"{file_prefix}{platform}_{aweme_id}_{index + 1}.{file_format}" if not with_watermark else f"{file_prefix}{platform}_{aweme_id}_{index + 1}_watermark.{file_format}"
                file_path = os.path.join(download_path, file_name)
                image_file_list.append(file_path)

                # 保存文件/Save file
                async with aiofiles.open(file_path, 'wb') as out_file:
                    await out_file.write(response.content)

            # 压缩文件/Compress file
            with zipfile.ZipFile(zip_file_path, 'w') as zip_file:
                for image_file in image_file_list:
                    zip_file.write(image_file, os.path.basename(image_file))

            # 返回压缩文件/Return compressed file
            return FileResponse(path=zip_file_path, filename=zip_file_name, media_type="application/zip")

    # 异常处理/Exception handling
    except Exception as e:
        print(e)
        code = 400
        return ErrorResponseModel(code=code, message=str(e), router=request.url.path, params=dict(request.query_params))

@router.get("/downloadAll", summary="下载用户所有作品")
async def download_user_works(
    request: Request,
    share_url: str = Query(..., description="用户分享链接"),
    base_folder: str = Query(default="downloads", description="下载保存路径"),
    with_watermark: bool = Query(default=False, description="是否下载带水印版本")
):
    """
    根据作品ID列表下载用户的所有作品，并按照视频和图片分类存储

    Args:
        nickname (str): 用户昵称，用于创建文件夹
        all_aweme_ids (list): 作品ID列表
        base_folder (str): 基础文件夹路径
        with_watermark (bool): 是否下载带水印版本，默认为False

    Returns:
        dict: 下载结果统计
    """
    import os
    import aiofiles
    import httpx
    import asyncio
    from datetime import datetime
    import json
    import zipfile
    result = await HybridCrawler.DouyinWebCrawler.get_all_user_videos(share_url)

    if not result.get("success", False):
        code = 400
        return ErrorResponseModel(code=code, message=result.get("error"), router=request.url.path,
                                  params=dict(request.query_params))
    nickname = result["user_info"]["nickname"]
    all_aweme_ids = result["aweme_ids"]

    # 清理昵称，确保可以作为文件夹名
    safe_nickname = "".join([c if c.isalnum() or c in " _-" else "_" for c in nickname])

    # 创建用户文件夹结构
    user_folder = os.path.join(base_folder, safe_nickname)
    video_folder = os.path.join(user_folder, "video")
    image_folder = os.path.join(user_folder, "image")

    os.makedirs(user_folder, exist_ok=True)
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(image_folder, exist_ok=True)

    print(f"用户: {nickname}")
    print(f"待下载作品数: {len(all_aweme_ids)}")
    print(f"保存目录: {user_folder}")

    # 下载统计
    download_stats = {
        "total": len(all_aweme_ids),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "video_count": 0,
        "image_count": 0,
        "details": []
    }

    # 获取headers
    kwargs = await HybridCrawler.DouyinWebCrawler.get_douyin_headers()

    # 下载每个作品
    for index, aweme_id in enumerate(all_aweme_ids):
        print(f"[{index + 1}/{len(all_aweme_ids)}] 正在处理作品: {aweme_id}")

        try:
            # 获取作品详情
            detail_response = await HybridCrawler.DouyinWebCrawler.fetch_one_video(aweme_id)
            if isinstance(detail_response, dict) and "data" in detail_response:
                detail_data = detail_response["data"]
            else:
                detail_data = detail_response

            aweme_detail = detail_data.get("aweme_detail", {})
            if not aweme_detail:
                print(f"获取作品详情失败: {aweme_id}")
                download_stats["failed"] += 1
                download_stats["details"].append({
                    "aweme_id": aweme_id,
                    "status": "failed",
                    "error": "获取详情失败"
                })
                continue

            # 提取基本信息
            desc = aweme_detail.get("desc", "").strip() or f"作品_{aweme_id}"
            create_time = datetime.fromtimestamp(aweme_detail.get("create_time", 0)).strftime("%Y%m%d")

            # 处理文件名，去除非法字符
            safe_desc = "".join([c if c.isalnum() or c in " _-" else "_" for c in desc])
            safe_desc = safe_desc[:50]  # 限制长度

            # 判断作品类型：视频或图片集
            if aweme_detail.get("images") is not None:
                # 处理图片集
                image_list = aweme_detail.get("images", [])
                if not image_list:
                    print(f"无法获取图片列表: {aweme_id}")
                    download_stats["failed"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "image",
                        "desc": desc,
                        "status": "failed",
                        "error": "无法获取图片列表"
                    })
                    continue

                # 创建作品专属文件夹
                image_set_folder = os.path.join(image_folder, f"{aweme_id}")
                os.makedirs(image_set_folder, exist_ok=True)

                image_success = 0
                image_failed = 0

                # 下载每张图片
                for img_index, img in enumerate(image_list):
                    img_filename = f"{img_index + 1}.jpg"
                    img_filepath = os.path.join(image_set_folder, img_filename)

                    # 检查图片是否已存在
                    if os.path.exists(img_filepath):
                        print(f"图片已存在，跳过下载: {img_filename}")
                        image_success += 1
                        continue

                    # 获取图片URL
                    url_list = img.get("url_list", [])
                    if not url_list:
                        print(f"无法获取图片URL: 图片{img_index + 1}")
                        image_failed += 1
                        continue

                    # 选择URL
                    img_url = url_list[0]  # 默认无水印

                    # 下载图片
                    try:
                        async with httpx.AsyncClient() as client:
                            response = await client.get(img_url, headers=kwargs["headers"], follow_redirects=True)
                            if response.status_code == 200:
                                async with aiofiles.open(img_filepath, 'wb') as f:
                                    await f.write(response.content)
                                print(f"下载成功: 图片{img_index + 1}")
                                image_success += 1
                            else:
                                print(f"下载图片失败，状态码: {response.status_code}")
                                image_failed += 1
                    except Exception as e:
                        print(f"下载图片出错: {e}")
                        image_failed += 1

                # 更新统计
                if image_failed == 0 and image_success > 0:
                    download_stats["success"] += 1
                    download_stats["image_count"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "image",
                        "desc": desc,
                        "folder": os.path.basename(image_set_folder),
                        "count": image_success,
                        "status": "success"
                    })
                elif image_success > 0:
                    download_stats["success"] += 1
                    download_stats["image_count"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "image",
                        "desc": desc,
                        "folder": os.path.basename(image_set_folder),
                        "count": image_success,
                        "failed": image_failed,
                        "status": "partial"
                    })
                else:
                    download_stats["failed"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "image",
                        "desc": desc,
                        "status": "failed",
                        "error": "所有图片下载失败"
                    })
                    # 删除空文件夹
                    try:
                        os.rmdir(image_set_folder)
                    except:
                        pass

            else:
                # 处理视频
                filename = f"{aweme_id}.mp4"
                filepath = os.path.join(video_folder, filename)

                # 检查视频是否已存在
                if os.path.exists(filepath):
                    print(f"视频已存在，跳过下载: {filename}")
                    download_stats["skipped"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "video",
                        "desc": desc,
                        "filename": filename,
                        "status": "skipped"
                    })
                    continue

                # 获取视频URL
                video_data = aweme_detail.get("video", {})
                play_addr = video_data.get("play_addr", {})
                download_addr = video_data.get("download_addr", {})

                # 选择合适的URL
                url_list = []
                if not with_watermark:
                    url_list = play_addr.get("url_list", [])
                else:
                    url_list = download_addr.get("url_list", [])

                if not url_list:
                    print(f"无法获取视频URL: {aweme_id}")
                    download_stats["failed"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "video",
                        "desc": desc,
                        "status": "failed",
                        "error": "无法获取视频URL"
                    })
                    continue

                video_url = url_list[0]

                # 下载视频
                print(f"正在下载视频: {filename}")
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(video_url, headers=kwargs["headers"], follow_redirects=True)
                        if response.status_code == 200:
                            async with aiofiles.open(filepath, 'wb') as f:
                                await f.write(response.content)
                            print(f"下载成功: {filename}")
                            download_stats["success"] += 1
                            download_stats["video_count"] += 1
                            download_stats["details"].append({
                                "aweme_id": aweme_id,
                                "type": "video",
                                "desc": desc,
                                "filename": filename,
                                "status": "success"
                            })
                        else:
                            print(f"下载失败，状态码: {response.status_code}")
                            download_stats["failed"] += 1
                            download_stats["details"].append({
                                "aweme_id": aweme_id,
                                "type": "video",
                                "desc": desc,
                                "filename": filename,
                                "status": "failed",
                                "error": f"HTTP状态码: {response.status_code}"
                            })
                except Exception as e:
                    print(f"下载视频出错: {e}")
                    download_stats["failed"] += 1
                    download_stats["details"].append({
                        "aweme_id": aweme_id,
                        "type": "video",
                        "desc": desc,
                        "filename": filename,
                        "status": "failed",
                        "error": str(e)
                    })

        except Exception as e:
            print(f"处理作品时出错: {e}")
            download_stats["failed"] += 1
            download_stats["details"].append({
                "aweme_id": aweme_id,
                "status": "failed",
                "error": str(e)
            })

        # 添加延迟避免请求过快
        await asyncio.sleep(15)

    # 保存下载统计
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats_file = os.path.join(user_folder, f"download_stats_{timestamp}.json")

    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump({
            "user_info": {
                "nickname": nickname,
                "downloaded_count": len(all_aweme_ids)
            },
            "download_stats": download_stats
        }, f, ensure_ascii=False, indent=2)

    print(f"下载完成，总共: {download_stats['total']}，成功: {download_stats['success']}，"
          f"失败: {download_stats['failed']}，跳过: {download_stats['skipped']}")
    print(f"视频: {download_stats['video_count']}，图片集: {download_stats['image_count']}")

    return download_stats