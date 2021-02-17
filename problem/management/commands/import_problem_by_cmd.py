from django.core.management.base import BaseCommand, CommandError
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from wsgiref.util import FileWrapper

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse

from account.decorators import problem_permission_required, ensure_created_by
from contest.models import Contest, ContestStatus
from fps.parser import FPSHelper, FPSParser
from judge.dispatcher import SPJCompiler
from options.options import SysOptions
from submission.models import Submission, JudgeStatus
from utils.api import APIView, CSRFExemptAPIView, validate_serializer, APIError
from utils.constants import Difficulty
from utils.shortcuts import rand_str, natural_sort_key
from utils.tasks import delete_files
from ...models import Problem, ProblemRuleType, ProblemTag, User
from ...serializers import (CreateContestProblemSerializer, CompileSPJSerializer,
                           CreateProblemSerializer, EditProblemSerializer, EditContestProblemSerializer,
                           ProblemAdminSerializer, TestCaseUploadForm, ContestProblemMakePublicSerializer,
                           AddContestProblemSerializer, ExportProblemSerializer,
                           ExportProblemRequestSerialzier, UploadProblemForm, ImportProblemSerializer,
                           FPSProblemSerializer)
from ...utils import TEMPLATE_BASE, build_problem_template
#from polls.models import Question as Poll


class Command(BaseCommand):
    help = 'Closes the specified poll for voting'
    
    def filter_name_list(self, name_list, spj, dir=""):
        ret = []
        prefix = 1
        if spj:
            while True:
                in_name = f"{prefix}.in"
                if f"{dir}{in_name}" in name_list:
                    ret.append(in_name)
                    prefix += 1
                    continue
                else:
                    return sorted(ret, key=natural_sort_key)
        else:
            while True:
                in_name = f"{prefix}.in"
                out_name = f"{prefix}.out"
                if f"{dir}{in_name}" in name_list and f"{dir}{out_name}" in name_list:
                    ret.append(in_name)
                    ret.append(out_name)
                    prefix += 1
                    continue
                else:
                    return sorted(ret, key=natural_sort_key)

    def process_zip(self, uploaded_zip_file, spj, dir=""):
        src_testcase_dir = uploaded_zip_file + dir
        name_list=os.listdir(src_testcase_dir)
        test_case_list = self.filter_name_list(name_list, spj=spj, dir='')
        if not test_case_list:
            raise APIError("Empty file")

        test_case_id = rand_str()
        test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
        os.mkdir(test_case_dir)
        os.chmod(test_case_dir, 0o710)

        size_cache = {}
        md5_cache = {}

        
        for item in test_case_list:
            with open(os.path.join(test_case_dir, item), "w") as f:
                with open(f"{src_testcase_dir}{item}") as fsrc:
                    content = fsrc.read().replace("\r\n", "\n")
                    size_cache[item] = len(content)
                if item.endswith(".out"):
                    md5_cache[item] = hashlib.md5(content.rstrip().encode('utf-8')).hexdigest()
                f.write(content)
        test_case_info = {"spj": spj, "test_cases": {}}

        info = []

        if spj:
            for index, item in enumerate(test_case_list):
                data = {"input_name": item, "input_size": size_cache[item]}
                info.append(data)
                test_case_info["test_cases"][str(index + 1)] = data
        else:
            # ["1.in", "1.out", "2.in", "2.out"] => [("1.in", "1.out"), ("2.in", "2.out")]
            test_case_list = zip(*[test_case_list[i::2] for i in range(2)])
            for index, item in enumerate(test_case_list):
                data = {"stripped_output_md5": md5_cache[item[1]],
                        "input_size": size_cache[item[0]],
                        "output_size": size_cache[item[1]],
                        "input_name": item[0],
                        "output_name": item[1]}
                info.append(data)
                test_case_info["test_cases"][str(index + 1)] = data

        with open(os.path.join(test_case_dir, "info"), "w", encoding="utf-8") as f:
            f.write(json.dumps(test_case_info, indent=4))

        for item in os.listdir(test_case_dir):
            os.chmod(os.path.join(test_case_dir, item), 0o640)

        return info, test_case_id
    
    def post(self, import_dir):
                    user = User.objects.get(id=1)
                    with open(import_dir + "/problem.json") as f:
                        problem_info = json.load(f)
                        serializer = ImportProblemSerializer(data=problem_info)
                        if not serializer.is_valid():
                            print("Invalid problem format, error is")
                            return False
                        else:
                            problem_info = serializer.data
                            for item in problem_info["template"].keys():
                                if item not in SysOptions.language_names:
                                    print("Unsupported language")
                                    return False

                        problem_info["display_id"] = problem_info["display_id"][:24]
                        
                        display_id = problem_info["display_id"]
                        sc = Problem.objects.filter(_id=display_id)
                        if sc.count()>0:
                            print('exited for display_id:%s' %(display_id))
                            return False
 


                        for k, v in problem_info["template"].items():
                            problem_info["template"][k] = build_problem_template(v["prepend"], v["template"],
                                                                                 v["append"])

                        spj = problem_info["spj"] is not None
                        rule_type = problem_info["rule_type"]
                        test_case_score = problem_info["test_case_score"]

                        # process test case
                        _, test_case_id = self.process_zip(import_dir, spj=spj, dir=f"testcase/")

                        problem_obj = Problem.objects.create(_id=problem_info["display_id"],
                                                             title=problem_info["title"],
                                                             description=problem_info["description"]["value"],
                                                             input_description=problem_info["input_description"][
                                                                 "value"],
                                                             output_description=problem_info["output_description"][
                                                                 "value"],
                                                             hint=problem_info["hint"]["value"],
                                                             test_case_score=test_case_score if test_case_score else [],
                                                             time_limit=problem_info["time_limit"],
                                                             memory_limit=problem_info["memory_limit"],
                                                             samples=problem_info["samples"],
                                                             template=problem_info["template"],
                                                             rule_type=problem_info["rule_type"],
                                                             source=problem_info["source"],
                                                             spj=spj,
                                                             spj_code=problem_info["spj"]["code"] if spj else None,
                                                             spj_language=problem_info["spj"][
                                                                 "language"] if spj else None,
                                                             spj_version=rand_str(8) if spj else "",
                                                             languages=SysOptions.language_names,
                                                             created_by=user,
                                                             visible=False,
                                                             difficulty=Difficulty.MID,
                                                             total_score=sum(item["score"] for item in test_case_score)
                                                             if rule_type == ProblemRuleType.OI else 0,
                                                             test_case_id=test_case_id
                                                             )
                        for tag_name in problem_info["tags"]:
                            tag_obj, _ = ProblemTag.objects.get_or_create(name=tag_name)
                            problem_obj.tags.add(tag_obj)
                    return True

    def add_arguments(self, parser):
        parser.add_argument('problem_dir', nargs=1, type=str)
        parser.add_argument('mode', nargs=1, type=str)

    def handle(self, *args, **options):
        print(options['mode'])
        succ_cnt = 0;
        if(options['mode'][0]=='batch'):
            root_dir = options['problem_dir'][0]
            name_list=os.listdir(root_dir)
            for curr_dir in name_list:
                proc_dir = root_dir + curr_dir + '/'
                print('processing one dir:',  proc_dir)
                ret = self.post(proc_dir)
                print(ret)
                if not ret:
                    continue
                succ_cnt = succ_cnt + 1
                if succ_cnt>=10:
                    break
        else:
            poll_id = options['problem_dir'][0]
            print('processing one dir:', poll_id)
            ret = self.post(poll_id)
            print(ret)

            self.stdout.write(self.style.SUCCESS('Successfully closed poll "%s"' % poll_id))
