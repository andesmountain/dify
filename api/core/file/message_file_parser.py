from typing import Dict, List, Optional, Union

import requests
from core.file.file_obj import FileObj, FileTransferMethod, FileType
from core.file.upload_file_parser import SUPPORT_EXTENSIONS
from extensions.ext_database import db
from models.account import Account
from models.model import AppModelConfig, EndUser, MessageFile, UploadFile


class MessageFileParser:

    def __init__(self, tenant_id: str, app_id: str) -> None:
        self.tenant_id = tenant_id
        self.app_id = app_id

    def validate_and_transform_files_arg(self, files: List[dict], app_model_config: AppModelConfig,
                                         user: Union[Account, EndUser]) -> List[FileObj]:
        """
        validate and transform files arg

        :param files:
        :param app_model_config:
        :param user:
        :return:
        """
        file_upload_config = app_model_config.file_upload_dict

        for file in files:
            if not isinstance(file, dict):
                raise ValueError('Invalid file format, must be dict')
            if not file.get('type'):
                raise ValueError('Missing file type')
            FileType.value_of(file.get('type'))
            if not file.get('transfer_method'):
                raise ValueError('Missing file transfer method')
            FileTransferMethod.value_of(file.get('transfer_method'))
            if file.get('transfer_method') == FileTransferMethod.REMOTE_URL.value:
                if not file.get('url'):
                    raise ValueError('Missing file url')
                if not file.get('url').startswith('http'):
                    raise ValueError('Invalid file url')
            if file.get('transfer_method') == FileTransferMethod.LOCAL_FILE.value and not file.get('upload_file_id'):
                raise ValueError('Missing file upload_file_id')

        # transform files to file objs
        type_file_objs = self._to_file_objs(files, file_upload_config)

        # validate files
        new_files = []
        for file_type, file_objs in type_file_objs.items():
            if file_type == FileType.IMAGE:
                # parse and validate files
                image_config = file_upload_config.get('image')

                # check if image file feature is enabled
                if not image_config['enabled']:
                    continue

                # Validate number of files
                if len(files) > image_config['number_limits']:
                    raise ValueError(f"Number of image files exceeds the maximum limit {image_config['number_limits']}")

                for file_obj in file_objs:
                    # Validate transfer method
                    if file_obj.transfer_method.value not in image_config['transfer_methods']:
                        raise ValueError(f'Invalid transfer method: {file_obj.transfer_method.value}')

                    # Validate file type
                    if file_obj.type != FileType.IMAGE:
                        raise ValueError(f'Invalid file type: {file_obj.type}')

                    if file_obj.transfer_method == FileTransferMethod.REMOTE_URL:
                        # check remote url valid and is image
                        result, error = self._check_image_remote_url(file_obj.url)
                        if result is False:
                            raise ValueError(error)
                    elif file_obj.transfer_method == FileTransferMethod.LOCAL_FILE:
                        # get upload file from upload_file_id
                        upload_file = (db.session.query(UploadFile)
                                       .filter(
                            UploadFile.id == file_obj.upload_file_id,
                            UploadFile.tenant_id == self.tenant_id,
                            UploadFile.created_by == user.id,
                            UploadFile.created_by_role == ('account' if isinstance(user, Account) else 'end_user'),
                            UploadFile.extension.in_(SUPPORT_EXTENSIONS)
                        ).first())

                        # check upload file is belong to tenant and user
                        if not upload_file:
                            raise ValueError('Invalid upload file')

                    new_files.append(file_obj)

        # return all file objs
        return new_files

    def transform_message_files(self, files: List[MessageFile], app_model_config: Optional[AppModelConfig]) -> List[FileObj]:
        """
        transform message files

        :param files:
        :param app_model_config:
        :return:
        """
        # transform files to file objs
        type_file_objs = self._to_file_objs(files, app_model_config.file_upload_dict)

        # return all file objs
        return [file_obj for file_objs in type_file_objs.values() for file_obj in file_objs]

    def _to_file_objs(self, files: List[Union[Dict, MessageFile]],
                      file_upload_config: dict) -> Dict[FileType, List[FileObj]]:
        """
        transform files to file objs

        :param files:
        :param file_upload_config:
        :return:
        """
        type_file_objs: Dict[FileType, List[FileObj]] = {
            # Currently only support image
            FileType.IMAGE: []
        }

        if not files:
            return type_file_objs

        # group by file type and convert file args or message files to FileObj
        for file in files:
            file_obj = self._to_file_obj(file, file_upload_config)
            if file_obj.type not in type_file_objs:
                continue

            type_file_objs[file_obj.type].append(file_obj)

        return type_file_objs

    def _to_file_obj(self, file: Union[dict, MessageFile], file_upload_config: dict) -> FileObj:
        """
        transform file to file obj

        :param file:
        :return:
        """
        if isinstance(file, dict):
            transfer_method = FileTransferMethod.value_of(file.get('transfer_method'))
            return FileObj(
                tenant_id=self.tenant_id,
                type=FileType.value_of(file.get('type')),
                transfer_method=transfer_method,
                url=file.get('url') if transfer_method == FileTransferMethod.REMOTE_URL else None,
                upload_file_id=file.get('upload_file_id') if transfer_method == FileTransferMethod.LOCAL_FILE else None,
                file_config=file_upload_config
            )
        else:
            return FileObj(
                id=file.id,
                tenant_id=self.tenant_id,
                type=FileType.value_of(file.type),
                transfer_method=FileTransferMethod.value_of(file.transfer_method),
                url=file.url,
                upload_file_id=file.upload_file_id or None,
                file_config=file_upload_config
            )

    def _check_image_remote_url(self, url):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            response = requests.head(url, headers=headers, allow_redirects=True)
            if response.status_code == 200:
                return True, ""
            else:
                return False, "URL does not exist."
        except requests.RequestException as e:
            return False, f"Error checking URL: {e}"
