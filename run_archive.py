"""Reversible visibility metadata. Never moves or rewrites run evidence."""
import datetime as dt
import shutil
import evaluation_store


def document(root):
    return evaluation_store.read(root/'archived-runs.json', {})


def is_archived(root, job):
    return bool(document(root).get(job))


def set_archived(root, job, archived):
    if type(archived) is not bool:raise ValueError('Archived must be true or false.')
    if not isinstance(job,str) or not job.isalnum():raise ValueError('Invalid run ID.')
    if not (root/'evaluations'/(job+'.json')).is_file():raise ValueError('Run not found.')
    with evaluation_store.LOCK:
        records=document(root)
        if bool(records.get(job)) == archived:return {'ok':True,'archived':archived}
        stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=root/'backups'/('archive-'+stamp);backup.mkdir(parents=True)
        path=root/'archived-runs.json'
        if path.exists():shutil.copy2(path,backup/path.name)
        else:evaluation_store.write(backup/path.name,{})
        if archived:records[job]={'archived_at':stamp}
        else:records.pop(job,None)
        evaluation_store.write(path,records)
    return {'ok':True,'archived':archived}
