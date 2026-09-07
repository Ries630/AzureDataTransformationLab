"""学習用landingから、指定された世代のCSVを上限付きで読み取る。"""

import os
import re

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.storage.blob import BlobClient
from validation import MAX_BYTES


class InputChangedError(Exception):
    """要求したETagと、現在の入力の世代が一致しない。"""


class StorageReadError(Exception):
    """入力内容を取得できず、業務上の判定を完了できない。"""


class StorageTimeoutError(StorageReadError):
    """Storageとの通信が規定時間内に完了しない。"""


def read_csv(path: str, etag: str) -> bytes:
    """固定Storageのlandingを条件付きGETし、上限超過を判定できる1バイトまで取得する。"""
    account = os.environ.get("LAB_STORAGE_ACCOUNT_NAME", "")
    if not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise RuntimeError("学習用Storage Account名が設定されていません。")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if os.environ.get("WEBSITE_HOSTNAME") and not client_id:
        raise RuntimeError("FunctionのManaged Identityが設定されていません。")
    credential = (
        ManagedIdentityCredential(client_id=client_id) if client_id else AzureCliCredential()
    )
    try:
        with (
            credential,
            BlobClient(
                account_url=f"https://{account}.blob.core.windows.net",
                container_name="landing",
                blob_name=path,
                credential=credential,
                connection_timeout=5,
                read_timeout=10,
                retry_total=1,
            ) as blob,
        ):
            try:
                return blob.download_blob(
                    offset=0,
                    length=MAX_BYTES + 1,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                    max_concurrency=1,
                    timeout=20,
                ).readall()
            except HttpResponseError as error:
                if error.status_code != 416:
                    raise
                # 空Blobへの範囲GETは416になる。同じ世代が空であることをHEADで確かめる。
                properties = blob.get_blob_properties(
                    etag=etag, match_condition=MatchConditions.IfNotModified, timeout=20
                )
                if properties.size == 0:
                    return b""
                raise
    except HttpResponseError as error:
        if error.status_code == 412:
            raise InputChangedError from error
        raise StorageReadError from error
    except (ServiceRequestError, ServiceResponseError) as error:
        # SDKの通信例外はタイムアウト以外も含むため、原因型で区別する。
        cause = error.inner_exception
        if isinstance(cause, TimeoutError) or (
            cause is not None and "Timeout" in type(cause).__name__
        ):
            raise StorageTimeoutError from error
        raise StorageReadError from error
