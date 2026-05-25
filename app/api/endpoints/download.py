import os
import zipfile
import json
from datetime import datetime

import aiofiles
import httpx
import yaml
from fastapi import APIRouter, Request, Query, HTTPException  # 导入FastAPI组件
from starlette.responses import FileResponse

from app.api.models.APIResponseModel import ErrorResponseModel  # 导入响应模型
from app.api import task_queue
from app.api.task_queue import RateLimiter, Task
from crawlers.hybrid.hybrid_crawler import HybridCrawler  # 导入混合数据爬虫
from crawlers.utils.logger import logger

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

# 下载视频专用
async def fetch_data_stream(url: str, request:Request , headers: dict = None, file_path: str = None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    } if headers is None else headers.get('headers')
    async with httpx.AsyncClient() as client:
        # 启用流式请求
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()

            # 流式保存文件
            async with aiofiles.open(file_path, 'wb') as out_file:
                async for chunk in response.aiter_bytes():
                    if await request.is_disconnected():
                        print("客户端断开连接，清理未完成的文件")
                        await out_file.close()
                        os.remove(file_path)
                        return False
                    await out_file.write(chunk)
            return True

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
            # response = await fetch_data(url, headers=__headers)

            success = await fetch_data_stream(url, request, headers=__headers, file_path=file_path)
            if not success:
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while fetching data"
                )

            # # 保存文件
            # async with aiofiles.open(file_path, 'wb') as out_file:
            #     await out_file.write(response.content)

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

def _sanitize_name(name: str) -> str:
    """把昵称/描述清洗成合法文件夹/文件名。"""
    return "".join([c if c.isalnum() or c in " _-" else "_" for c in name])


async def _stream_download(url: str, headers: dict, file_path: str) -> bool:
    """流式下载单个 URL 到 file_path，避免大文件占满内存。失败会清理半成品。"""
    tmp_path = file_path + ".part"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                resp.raise_for_status()
                async with aiofiles.open(tmp_path, "wb") as out:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        await out.write(chunk)
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        logger.warning(f"流式下载失败 {url}: {e}")
        for p in (tmp_path, file_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        return False


async def _run_user_download(task: Task, limiter: RateLimiter) -> dict:
    """worker 实际执行的下载逻辑。所有抖音 API 调用都过 limiter；CDN 媒体下载不限速。"""
    share_url: str = task.params["share_url"]
    with_watermark: bool = task.params.get("with_watermark", False)
    base_folder = task.params.get("base_folder", "downloads")

    # 第一次 API 调用：拿用户全部作品 id 列表
    await limiter.acquire()
    result = await HybridCrawler.DouyinWebCrawler.get_all_user_videos(share_url)
    if not result.get("success", False):
        raise RuntimeError(result.get("error") or "get_all_user_videos failed")

    nickname = _sanitize_name(result["user_info"]["nickname"])
    all_aweme_ids = result["new_aweme_ids"]

    user_folder = os.path.join(base_folder, nickname)
    video_folder = os.path.join(user_folder, "video")
    image_folder = os.path.join(user_folder, "image")
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(image_folder, exist_ok=True)

    stats = {
        "total": len(all_aweme_ids),
        "URL": share_url,
        "nickname": nickname,
        "user_folder": user_folder,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "video_count": 0,
        "image_count": 0,
        "processed": 0,
        "details": [],
    }
    task_queue.update_progress(task, dict(stats, current=None))
    logger.info(f"[downloadAll] 用户={nickname} 待下载={len(all_aweme_ids)} 目录={user_folder}")

    kwargs = await HybridCrawler.DouyinWebCrawler.get_douyin_headers()

    for index, aweme_id in enumerate(all_aweme_ids):
        logger.info(f"[downloadAll] [{index + 1}/{len(all_aweme_ids)}] 处理: {aweme_id}")
        task_queue.update_progress(
            task,
            dict(stats, current={"aweme_id": aweme_id, "index": index + 1}),
        )

        try:
            await limiter.acquire()
            detail_response = await HybridCrawler.DouyinWebCrawler.fetch_one_video(aweme_id)
            detail_data = detail_response.get("data", detail_response) if isinstance(detail_response, dict) else {}
            aweme_detail = (detail_data or {}).get("aweme_detail") or {}
            if not aweme_detail:
                stats["failed"] += 1
                stats["details"].append({"aweme_id": aweme_id, "status": "failed", "error": "获取详情失败"})
                continue

            desc = aweme_detail.get("desc", "").strip() or f"作品_{aweme_id}"

            if aweme_detail.get("images") is not None:
                # ---- 图集 ----
                image_list = aweme_detail.get("images") or []
                if not image_list:
                    stats["failed"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "image", "desc": desc,
                         "status": "failed", "error": "无法获取图片列表"}
                    )
                    continue

                image_success = 0
                image_failed = 0
                for img_index, img in enumerate(image_list):
                    img_filename = f"{aweme_id}-{img_index + 1}.jpg"
                    img_filepath = os.path.join(image_folder, img_filename)
                    if os.path.exists(img_filepath):
                        image_success += 1
                        continue
                    url_list = img.get("url_list") or []
                    if not url_list:
                        image_failed += 1
                        continue
                    ok = await _stream_download(url_list[0], kwargs["headers"], img_filepath)
                    if ok:
                        image_success += 1
                    else:
                        image_failed += 1

                if image_success > 0 and image_failed == 0:
                    stats["success"] += 1
                    stats["image_count"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "image", "desc": desc,
                         "folder": os.path.basename(image_folder),
                         "count": image_success, "status": "success"}
                    )
                elif image_success > 0:
                    stats["success"] += 1
                    stats["image_count"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "image", "desc": desc,
                         "folder": os.path.basename(image_folder),
                         "count": image_success, "failed": image_failed, "status": "partial"}
                    )
                else:
                    stats["failed"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "image", "desc": desc,
                         "status": "failed", "error": "所有图片下载失败"}
                    )

            else:
                # ---- 视频 ----
                filename = f"{aweme_id}.mp4"
                filepath = os.path.join(video_folder, filename)
                if os.path.exists(filepath):
                    stats["skipped"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "video", "desc": desc,
                         "filename": filename, "status": "skipped"}
                    )
                    continue

                video_data = aweme_detail.get("video") or {}
                addr = video_data.get("play_addr") if not with_watermark else video_data.get("download_addr")
                url_list = (addr or {}).get("url_list") or []
                if not url_list:
                    stats["failed"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "video", "desc": desc,
                         "status": "failed", "error": "无法获取视频URL"}
                    )
                    continue

                ok = await _stream_download(url_list[0], kwargs["headers"], filepath)
                if ok:
                    stats["success"] += 1
                    stats["video_count"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "video", "desc": desc,
                         "filename": filename, "status": "success"}
                    )
                else:
                    stats["failed"] += 1
                    stats["details"].append(
                        {"aweme_id": aweme_id, "type": "video", "desc": desc,
                         "filename": filename, "status": "failed", "error": "stream download failed"}
                    )

        except Exception as e:
            logger.exception(f"[downloadAll] 处理 {aweme_id} 异常")
            stats["failed"] += 1
            stats["details"].append({"aweme_id": aweme_id, "status": "failed", "error": str(e)})

        stats["processed"] = index + 1
        task_queue.update_progress(task, dict(stats, current={"aweme_id": aweme_id, "index": index + 1}))

    # 保存最终统计
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats_file = os.path.join(user_folder, f"download_stats_{timestamp}.json")
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump({"user_info": result["user_info"], "download_stats": stats}, f, ensure_ascii=False, indent=2)
    stats["stats_file"] = stats_file

    logger.info(
        f"[downloadAll] 完成: total={stats['total']} success={stats['success']} "
        f"failed={stats['failed']} skipped={stats['skipped']} "
        f"video={stats['video_count']} image={stats['image_count']}"
    )
    return stats


@router.get("/downloadAll", summary="下载用户所有作品（异步任务）")
async def download_user_works(
    request: Request,
    share_url: str = Query(..., description="用户分享链接"),
    with_watermark: bool = Query(default=False, description="是否下载带水印版本"),
):
    """投递一个「下载用户全部作品」任务到队列。

    返回 task_id 后立即结束请求，实际下载由后台 worker 串行执行，
    两次出站抖音 API 之间会强制 ~5s 间隔（±30% 抖动）以避免 Cookie 风控。

    用 `GET /api/task/{task_id}` 查询进度和结果。
    """
    task = task_queue.submit(
        kind="download_user_all",
        params={"share_url": share_url, "with_watermark": with_watermark},
        runner=_run_user_download,
    )
    return {
        "code": 200,
        "task_id": task.id,
        "status": task.status.value,
        "status_url": f"/api/task/{task.id}",
        "message": "任务已入队，请通过 status_url 查询进度",
    }