"""
main.py — HBV FastAPI gateway running on the HPC head node.

Start with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

JupyterHub injects the logged-in username as the X-User header on every
proxied request, so we use that for per-user identity and rate limiting.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db

# ── Config ────────────────────────────────────────────────────────────────
MAX_CONCURRENT_JOBS_PER_USER = int(os.environ.get('MAX_CONCURRENT_JOBS', '3'))

# When DEV_MODE=1, hbv_worker.py is called directly (no sbatch needed).
# On the real HPC head node leave DEV_MODE unset.
# LOCAL=1  → mock sbatch (bin/) + hbv_run_local.sh (no Singularity)
# DEV_MODE=1 → skip sbatch entirely, run worker in-process thread (fastest)
# Neither set → real HPC: sbatch + hbv_run.sh + Singularity
LOCAL   = os.environ.get('LOCAL',    '0') == '1'
DEV_MODE = os.environ.get('DEV_MODE', '0') == '1'

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

NFS_ROOT     = os.environ.get('HBV_NFS_ROOT',    '/data/hbv')
OUTPUT_ROOT  = os.environ.get('HBV_OUTPUT_ROOT',
                               os.path.join(_REPO_ROOT, 'local_output') if LOCAL else f'{NFS_ROOT}/output')
UPLOAD_ROOT  = os.environ.get('HBV_UPLOAD_ROOT',
                               os.path.join(_REPO_ROOT, 'local_uploads') if LOCAL else f'{NFS_ROOT}/uploads')
SLURM_SCRIPT = os.environ.get('HBV_SLURM_SH',
                               os.path.join(_REPO_ROOT, 'slurm', 'hbv_run_local.sh') if LOCAL
                               else f'{NFS_ROOT}/slurm/hbv_run.sh')
WORKER_SCRIPT = os.environ.get('HBV_WORKER',
                                os.path.join(_REPO_ROOT, 'compute', 'hbv_worker.py'))

# Prepend bin/ (mock sbatch/squeue/scancel) to PATH when running locally
if LOCAL:
    _bin = os.path.join(_REPO_ROOT, 'bin')
    os.environ['PATH'] = f'{_bin}:{os.environ.get("PATH", "")}'

# ── App ───────────────────────────────────────────────────────────────────
app = FastAPI(title='HBV Gateway', version='1.0')

# HBV_CORS_ORIGINS: comma-separated list of allowed origins.
# Set to your JupyterHub URL in production, e.g.:
#   HBV_CORS_ORIGINS=https://jupyter.rahti.csc.fi
# Defaults to '*' for local dev only.
_CORS_ORIGINS = [o.strip() for o in
                 os.environ.get('HBV_CORS_ORIGINS', '*').split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=['GET', 'POST', 'DELETE'],
    allow_headers=['*'],
)


@app.on_event('startup')
async def startup():
    os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_ROOT, exist_ok=True)
    await db.init_db()


# ── Auth helper ───────────────────────────────────────────────────────────
def get_user(x_user: Annotated[str | None, Header(alias='X-User')] = None) -> str:
    """
    JupyterHub proxy injects X-User with the logged-in username.
    For local dev without JupyterHub, HBV_DEV_USER env var is used as fallback.
    """
    user = x_user or os.environ.get('HBV_DEV_USER')
    if not user:
        raise HTTPException(status_code=401, detail='X-User header missing')
    return user


UserDep = Annotated[str, Depends(get_user)]


# ── Request / response models ─────────────────────────────────────────────
class SubmitRequest(BaseModel):
    catchment_ids:          list[str] = Field(..., min_length=1)
    shapefile_path:         str
    id_col:                 str = Field(default='TASO_ID',
                                        description='Column name for catchment IDs in the shapefile')
    precipitation_nc:       str
    evapotranspiration_nc:  str
    temperature_nc:         str
    urban_land_path:        str
    agricultural_land_path: str
    hbvpara_path:           str = Field(default='/app/hbv_para.csv')
    n_nodes:                int = Field(default=4, ge=1, le=64,
                                        description='Number of Slurm array tasks (one per node)')
    cpus_per_task:          int = Field(default=4, ge=1, le=128,
                                        description='CPUs per Slurm task')


class JobResponse(BaseModel):
    job_id:       str
    slurm_id:     str | None
    status:       str
    catchments:   list[str]
    submitted_at: str
    finished_at:  str | None
    output_dir:   str | None
    error_msg:    str | None


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.post('/submit', response_model=JobResponse, status_code=202)
async def submit_job(body: SubmitRequest, user: UserDep):
    """Submit a new HBV run to Slurm."""
    active = await db.count_active_jobs(user)
    if active >= MAX_CONCURRENT_JOBS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f'You already have {active} active jobs '
                   f'(limit is {MAX_CONCURRENT_JOBS_PER_USER}). '
                   'Wait for one to finish before submitting again.',
        )

    job_id = str(uuid.uuid4())
    output_dir = os.path.join(OUTPUT_ROOT, job_id)
    os.makedirs(output_dir, exist_ok=True)

    # Build environment so hbv_worker can find all input paths
    env = {
        **os.environ,
        'HBV_JOB_ID':            job_id,
        'HBV_OUTPUT_DIR':         output_dir,
        'HBV_SHAPEFILE':          body.shapefile_path,
        'HBV_PRECIP_NC':          body.precipitation_nc,
        'HBV_ET_NC':              body.evapotranspiration_nc,
        'HBV_TEMP_NC':            body.temperature_nc,
        'HBV_URBAN_PATH':         body.urban_land_path,
        'HBV_AGRI_PATH':          body.agricultural_land_path,
        'HBV_PARA_PATH':          body.hbvpara_path,
        'HBV_CATCHMENT_IDS':      ','.join(body.catchment_ids),
        'HBV_ID_COL':             body.id_col,
        'HBV_USER':               user,
        'HBV_CPUS_PER_TASK':      str(body.cpus_per_task),
    }

    if DEV_MODE and not LOCAL:
        # ── Dev mode: run hbv_worker.py directly in a background thread ──
        slurm_id = f'dev-{job_id[:8]}'
        await db.insert_job(job_id, user, body.catchment_ids,
                            slurm_id=slurm_id, output_dir=output_dir)
        await db.update_status(job_id, 'running')

        def _run_local():
            worker = os.path.abspath(WORKER_SCRIPT)
            cmd = [
                sys.executable, worker,
                '--job-id',    job_id,
                '--task',      '0',
                '--total',     '1',
                '--shapefile', body.shapefile_path,
                '--precip-nc', body.precipitation_nc,
                '--et-nc',     body.evapotranspiration_nc,
                '--temp-nc',   body.temperature_nc,
                '--urban-path', body.urban_land_path,
                '--agri-path', body.agricultural_land_path,
                '--para-csv',  body.hbvpara_path,
                '--catchments', ','.join(body.catchment_ids),
                '--output',    output_dir,
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    asyncio.run(db.update_status(job_id, 'done'))
                else:
                    asyncio.run(db.update_status(job_id, 'failed',
                                                 error_msg=result.stderr[-2000:]))
            except Exception as exc:
                asyncio.run(db.update_status(job_id, 'failed', error_msg=str(exc)))

        threading.Thread(target=_run_local, daemon=True).start()

    else:
        # ── sbatch path: LOCAL uses mock bin/sbatch; HPC uses real sbatch ─
        array_arg = f'0-{body.n_nodes - 1}'
        try:
            result = subprocess.run(
                ['sbatch', f'--array={array_arg}',
                 f'--cpus-per-task={body.cpus_per_task}',
                 SLURM_SCRIPT],
                capture_output=True, text=True, check=True, env=env,
            )
            slurm_id = result.stdout.strip().split()[-1]
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=500,
                                detail=f'sbatch failed: {exc.stderr.strip()}')
        except FileNotFoundError:
            raise HTTPException(status_code=500,
                                detail='sbatch not found — add bin/ to PATH for local testing')

        await db.insert_job(job_id, user, body.catchment_ids,
                            slurm_id=slurm_id, output_dir=output_dir)

    job = await db.get_job(job_id)
    return job


@app.get('/status/{job_id}', response_model=JobResponse)
async def get_status(job_id: str, user: UserDep):
    """Poll the status of a previously submitted job."""
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['user_id'] != user:
        raise HTTPException(status_code=403, detail='Not your job')

    # LOCAL mode: check for .task_N_done marker files written by hbv_run_local.sh
    if LOCAL and job['status'] in ('queued', 'running') and job.get('output_dir'):
        new_status = _check_local_done(job['output_dir'], job.get('slurm_id'))
        if new_status and new_status != job['status']:
            await db.update_status(job_id, new_status)
            job['status'] = new_status

    # HPC mode: check task_status.json files first, then fall back to squeue/sacct
    if not DEV_MODE and not LOCAL and job['status'] in ('queued', 'running') and job.get('output_dir'):
        task_status = _check_task_status_json(job['output_dir'], job.get('slurm_id'))
        if task_status:
            if task_status != job['status']:
                await db.update_status(job_id, task_status)
                job['status'] = task_status
        elif job.get('slurm_id'):
            slurm_status = _query_slurm(job['slurm_id'])
            if slurm_status and slurm_status != job['status']:
                await db.update_status(job_id, slurm_status)
                job['status'] = slurm_status

    return job


@app.get('/results/{job_id}')
async def get_results(job_id: str, user: UserDep):
    """Return output file paths once the job is done."""
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['user_id'] != user:
        raise HTTPException(status_code=403, detail='Not your job')
    if job['status'] != 'done':
        raise HTTPException(status_code=409,
                            detail=f'Job is {job["status"]}, not done yet')

    output_dir = job['output_dir']
    if not output_dir or not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail='Output directory not found')

    # Walk output_dir and list all CSV files per catchment
    files: dict[str, list[str]] = {}
    for entry in os.scandir(output_dir):
        if entry.is_dir():
            csvs = sorted(
                f.path for f in os.scandir(entry.path) if f.name.endswith('.csv')
            )
            if csvs:
                files[entry.name] = csvs

    return {'job_id': job_id, 'output_dir': output_dir, 'files': files}


@app.get('/cluster/info')
async def cluster_info(user: UserDep):
    """Return live Slurm cluster resource summary."""
    info = {'nodes': [], 'summary': {}}
    try:
        # sinfo -h -o: nodename, state, CPUs (A/I/O/T = allocated/idle/other/total)
        r = subprocess.run(
            ['sinfo', '-h', '--Node', '-o', '%N %t %C %m'],
            capture_output=True, text=True, timeout=10,
        )
        nodes = []
        total_cpus = idle_cpus = alloc_cpus = 0
        for line in r.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            name, state, cpu_str = parts[0], parts[1], parts[2]
            mem_mb = int(parts[3]) if len(parts) > 3 else 0
            a, i, o, t = (int(x) for x in cpu_str.split('/'))
            nodes.append({
                'name': name, 'state': state,
                'cpus_alloc': a, 'cpus_idle': i, 'cpus_total': t,
                'mem_gb': round(mem_mb / 1024, 1),
            })
            total_cpus += t; idle_cpus += i; alloc_cpus += a
        info['nodes'] = nodes
        info['summary'] = {
            'total_nodes': len(nodes),
            'idle_nodes': sum(1 for n in nodes if n['state'] in ('idle', 'idle*')),
            'total_cpus': total_cpus,
            'idle_cpus': idle_cpus,
            'alloc_cpus': alloc_cpus,
        }
    except Exception as exc:
        info['error'] = str(exc)
    return info


@app.get('/jobs/mine', response_model=list[JobResponse])
async def my_jobs(user: UserDep):
    """List all jobs submitted by the current user."""
    return await db.get_user_jobs(user)


@app.get('/download/{job_id}/{catchment}/{filename}')
async def download_file(job_id: str, catchment: str, filename: str, user: UserDep):
    """Download a single output CSV file."""
    from fastapi.responses import FileResponse
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['user_id'] != user:
        raise HTTPException(status_code=403, detail='Not your job')
    path = os.path.join(job['output_dir'], catchment, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail='File not found')
    return FileResponse(path, filename=filename, media_type='text/csv')


@app.delete('/jobs/{job_id}', status_code=204)
async def cancel_job(job_id: str, user: UserDep):
    """Cancel a queued or running job."""
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['user_id'] != user:
        raise HTTPException(status_code=403, detail='Not your job')
    if job['status'] not in ('queued', 'running'):
        raise HTTPException(status_code=409,
                            detail=f'Cannot cancel a job with status={job["status"]}')

    if job.get('slurm_id'):
        try:
            subprocess.run(['scancel', job['slurm_id']], check=True,
                           capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=500,
                                detail=f'scancel failed: {exc.stderr.strip()}')

    await db.update_status(job_id, 'cancelled')


@app.get('/queue')
async def queue_overview(_: UserDep):
    """Admin view — all recent jobs across all users."""
    return await db.all_jobs(limit=200)


@app.get('/logs/{job_id}')
async def get_logs(job_id: str, user: UserDep, offset: int = 0):
    """
    Return stdout/stderr from the job's log files, starting at byte `offset`.
    The dashboard calls this on each poll and appends only the new bytes,
    so logs stream in incrementally without re-sending everything each time.
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['user_id'] != user:
        raise HTTPException(status_code=403, detail='Not your job')

    output_dir = job.get('output_dir', '')
    if not output_dir:
        return {'lines': [], 'next_offset': 0}

    log_dir = os.path.join(output_dir, 'logs')
    if not os.path.isdir(log_dir):
        # Also check one level up (HPC writes logs there too)
        log_dir = output_dir

    import glob
    log_files = sorted(
        glob.glob(os.path.join(log_dir, '*.out')) +
        glob.glob(os.path.join(log_dir, '*.err'))
    )

    # Read all log content as one blob, skip `offset` bytes already sent
    blob = ''
    for lf in log_files:
        try:
            blob += open(lf).read()
        except OSError:
            pass

    new_content = blob[offset:]
    lines = [l for l in new_content.splitlines() if l.strip()]
    return {'lines': lines, 'next_offset': offset + len(new_content)}


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.post('/upload')
async def upload_file(user: UserDep, file: UploadFile = File(...)):
    """
    Upload a data file (shapefile zip, NetCDF, land-use zip) from JupyterHub
    to the HPC NFS. Files are deduplicated by MD5 hash so re-uploading the
    same data is instant.

    Returns:
        { "path": "/data/hbv/uploads/<md5>/<filename>",
          "cached": true/false }
    """
    # Stream into a temp buffer to compute MD5 without loading into RAM
    hasher = hashlib.md5()
    tmp_path = os.path.join(UPLOAD_ROOT, f'_tmp_{uuid.uuid4().hex}')
    os.makedirs(UPLOAD_ROOT, exist_ok=True)

    try:
        with open(tmp_path, 'wb') as f:
            while chunk := await file.read(1024 * 1024):   # 1 MB chunks
                hasher.update(chunk)
                f.write(chunk)

        file_hash = hasher.hexdigest()
        dest_dir  = os.path.join(UPLOAD_ROOT, file_hash)
        dest_path = os.path.join(dest_dir, file.filename)

        # If already uploaded, return cached path immediately
        if os.path.exists(dest_path):
            return {'path': dest_path, 'cached': True}

        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(tmp_path, dest_path)

        # If it's a zip (shapefile bundle), extract alongside the zip
        if file.filename.lower().endswith('.zip'):
            extract_dir = os.path.join(dest_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(dest_path) as z:
                z.extractall(extract_dir)
            # Find the .shp file if present; return its path instead
            shp_files = [
                os.path.join(dp, fn)
                for dp, _, fns in os.walk(extract_dir)
                for fn in fns if fn.lower().endswith('.shp')
            ]
            if shp_files:
                return {'path': shp_files[0], 'cached': False}

        return {'path': dest_path, 'cached': False}

    except Exception as exc:
        # Clean up temp file on error
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────

def _check_local_done(output_dir: str, slurm_id: str | None) -> str | None:
    """
    In LOCAL mode the Slurm script writes .task_N_done marker files.
    If at least one task marker exists, read it for the status.
    If any task failed, the whole job is 'failed'.
    """
    import glob
    markers = glob.glob(os.path.join(output_dir, '.task_*_done'))
    if not markers:
        return None   # still running
    statuses = set()
    for m in markers:
        try:
            statuses.add(open(m).read().strip())
        except OSError:
            pass
    if 'failed' in statuses:
        return 'failed'
    if statuses == {'done'}:
        return 'done'
    return None


def _check_task_status_json(output_dir: str, slurm_id: str | None) -> str | None:
    """
    HPC mode: hbv_run.sh writes task_N_status.json files per array task.
    Returns 'done', 'failed', or None (still running).
    """
    import glob, json as _json
    files = glob.glob(os.path.join(output_dir, 'task_*_status.json'))
    if not files:
        return None
    any_failed = False
    for f in files:
        try:
            data = _json.loads(open(f).read())
            if data.get('errors', 0) > 0:
                any_failed = True
        except (OSError, ValueError):
            pass
    if any_failed:
        return 'failed'
    return 'done'


# ── Slurm helpers ─────────────────────────────────────────────────────────

def _query_slurm(slurm_id: str) -> str | None:
    """
    Ask squeue for the job state. Returns a normalised status string or None
    if squeue is unavailable (e.g. during local dev/testing).
    """
    try:
        result = subprocess.run(
            ['squeue', '--job', slurm_id, '--noheader', '--format=%T'],
            capture_output=True, text=True, timeout=10,
        )
        state = result.stdout.strip().upper()
        if not state:
            # Job not in squeue — it finished (done or failed)
            # Check sacct for the final state
            sacct = subprocess.run(
                ['sacct', '--job', slurm_id, '--noheader',
                 '--format=State', '--parsable2'],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l.strip() for l in sacct.stdout.strip().splitlines() if l.strip()]
            if lines:
                raw = lines[0].split('|')[0].upper()
                if 'COMPLETE' in raw:
                    return 'done'
                elif 'FAIL' in raw or 'CANCEL' in raw:
                    return 'failed'
            return 'done'   # conservative: assume done if we can't tell
        # Map Slurm states to our vocabulary
        if state in ('PENDING', 'CONFIGURING', 'RESIZING'):
            return 'queued'
        if state in ('RUNNING', 'COMPLETING'):
            return 'running'
        if 'COMPLETE' in state:
            return 'done'
        if 'CANCEL' in state:
            return 'cancelled'
        return 'failed'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
