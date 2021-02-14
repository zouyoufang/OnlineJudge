import dramatiq

from account.models import User
from submission.models import Submission
from judge.dispatcher import JudgeDispatcher
from utils.shortcuts import DRAMATIQ_WORKER_ARGS


@dramatiq.actor(**DRAMATIQ_WORKER_ARGS())
def judge_task(submission_id, problem_id):
    from utils.ojlog import logger
    logger.info('into judge task')
    uid = Submission.objects.get(id=submission_id).user_id
    if User.objects.get(id=uid).is_disabled:
        logger.info('user disabled')
        return
    logger.info('get dispatcher')
    JudgeDispatcher(submission_id, problem_id).judge()
