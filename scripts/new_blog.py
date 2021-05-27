import argparse
import datetime

import random
import threading
import time
import logging

from pathlib import Path


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


class InvalidSystemClock(Exception):
    """
    时钟回拨异常
    """

    pass


class IdWorker(object):
    """
    用于生成IDs
    """

    # 64位ID的划分
    WORKER_ID_BITS = 5
    DATACENTER_ID_BITS = 5
    SEQUENCE_BITS = 12

    # 最大取值计算
    MAX_WORKER_ID = -1 ^ (-1 << WORKER_ID_BITS)  # 2**5-1 0b11111
    MAX_DATACENTER_ID = -1 ^ (-1 << DATACENTER_ID_BITS)

    # 移位偏移计算
    WOKER_ID_SHIFT = SEQUENCE_BITS
    DATACENTER_ID_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS
    TIMESTAMP_LEFT_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS + DATACENTER_ID_BITS

    # 序号循环掩码
    SEQUENCE_MASK = -1 ^ (-1 << SEQUENCE_BITS)

    # Twitter元年时间戳
    TWEPOCH = 1288834974657

    def __init__(self, datacenter_id, worker_id, sequence=0):
        """
        初始化
        :param datacenter_id: 数据中心（机器区域）ID
        :param worker_id: 机器ID
        :param sequence: 其实序号
        """
        # sanity check
        if worker_id > self.MAX_WORKER_ID or worker_id < 0:
            raise ValueError("worker_id值越界")

        if datacenter_id > self.MAX_DATACENTER_ID or datacenter_id < 0:
            raise ValueError("datacenter_id值越界")

        self.worker_id = worker_id
        self.datacenter_id = datacenter_id
        self.sequence = sequence

        self.last_timestamp = -1  # 上次计算的时间戳

    def _gen_timestamp(self):
        """
        生成整数时间戳
        :return:int timestamp
        """
        return int(time.time() * 1000)

    def get_id(self):
        """
        获取新ID
        :return:
        """
        timestamp = self._gen_timestamp()

        # 时钟回拨
        if timestamp < self.last_timestamp:
            logging.error("时钟向后移动. 拒绝请求，直到 {}".format(self.last_timestamp))
            raise InvalidSystemClock

        if timestamp == self.last_timestamp:
            self.sequence = (self.sequence + 1) & self.SEQUENCE_MASK
            if self.sequence == 0:
                timestamp = self._til_next_millis(self.last_timestamp)
        else:
            self.sequence = 0

        self.last_timestamp = timestamp

        new_id = (
            ((timestamp - self.TWEPOCH) << self.TIMESTAMP_LEFT_SHIFT)
            | (self.datacenter_id << self.DATACENTER_ID_SHIFT)
            | (self.worker_id << self.WOKER_ID_SHIFT)
            | self.sequence
        )
        return new_id

    def _til_next_millis(self, last_timestamp):
        """
        等到下一毫秒
        """
        timestamp = self._gen_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._gen_timestamp()
        return timestamp


class FileWorker:
    def __init__(
        self,
        path,
        title_id,
        title,
        subtitle,
        author,
        photo_path,
        catalog,
        tags="python",
        description="",
        date=datetime.date.today().strftime("%Y-%m-%d"),
    ):
        if not path or not title_id or not title:
            logging.error(f"path: {path}, title_id: {title_id}, title: {title}")
            raise KeyError("缺少必要信息, 至少使用 -t 指定文章名称")
        self.path = path
        self.title_id = title_id
        self.file_name = f"{date}-{title_id}"
        self.title = title
        self.subtitle = subtitle
        self.author = author
        self.photo_path = photo_path
        self.catalog = catalog
        self.tags = tags.split(",")
        self.description = description
        self.date = date

    @property
    def build_header_info(self):

        header_list = [val.name for val in self.photo_path.iterdir()]
        header_image = header_list[random.randint(0, len(header_list) - 1)]

        header = [
            "---",
            f"title: {self.title}",
            f"subtitle: {self.subtitle}",
            f"author: {self.author}",
            f"date: {self.date}",
            f"header_img: /img/in-post/header/{header_image}",
            f"catalog: {self.catalog}",
            "tags:",
            "\n".join([f"  - {val}" for val in self.tags]),
            "---",
            f"\n{self.description}",
            "\n<!-- more -->\n",
        ]
        return [f"{val}\n" for val in header]

    def _write_blog(self, file_name, info):
        logger.warning(
            f"线程 :: {threading.currentThread().native_id} 启动写入 {file_name} 任务"
        )
        try:
            with open(file_name, "w+") as f:
                f.writelines(info)
        except Exception as e:
            logger.error(f"无法写入文件: {e}")

    def _write_index(self, file_name, info):
        logger.warning(f"线程 :: {threading.currentThread().native_id} 启动写入 索引 任务")
        try:
            with open(file_name, "a+") as sl:
                sl.write(info)
        except Exception as e:
            logger.error(f"文章索引未记录，请手动添加: {e}")

    def wirte_file(self):
        header = self.build_header_info
        task_blog = threading.Thread(
            target=self._write_blog,
            args=[self.path / f"posts/{self.file_name}.md", header],
        )
        task_index = threading.Thread(
            target=self._write_index,
            args=[self.path / "slug_title.txt", f"{self.title_id}:{self.title}\n"],
        )
        for task in (task_blog, task_index):
            task.start()
            task.join()


if __name__ == "__main__":

    """
    eg:
        python scripts/new_blog.py -t "xxxxx" -s "分类" -ts "标签1" -d "简介摘要"
    """

    parser = argparse.ArgumentParser(description="文章描述信息")
    parser.add_argument("-t", "--title", type=str, default="", help="文章姓名")
    parser.add_argument("-s", "--subtitle", type=str, default="文章暂存", help="文章分类")
    parser.add_argument("-a", "--author", type=str, default="systemime", help="作者")
    parser.add_argument(
        "-p",
        "--photo",
        type=str,
        default=Path(__file__).resolve(strict=True).parent.parent
        / "blog/.vuepress/public/img/in-post/header",
        help="图片地址",
    )
    parser.add_argument("-c", "--catalog", type=bool, default=True, help="是否开启目录")
    parser.add_argument("-ts", "--tags", type=str, default="python", help="多个tag以,分割")
    parser.add_argument("-d", "--description", type=str, default="", help="文章摘要")
    parser.add_argument(
        "-P",
        "--path",
        type=str,
        default=Path(__file__).resolve(strict=True).parent.parent / "blog",
        help="博客路径",
    )
    args = parser.parse_args()

    worker = IdWorker(1, 1, 0)
    title_id = worker.get_id()

    logger.info(f"GET titile_id >>> {title_id}")

    f_worker = FileWorker(
        Path(args.path),
        title_id,
        args.title,
        args.subtitle,
        args.author,
        Path(args.photo),
        args.catalog,
        tags=args.tags,
        description=args.description,
    )

    logger.warning(f"{datetime.datetime.now()} :: 正在创建")
    f_worker.wirte_file()
    logger.warning(f"{datetime.datetime.now()} :: 创建完成")
