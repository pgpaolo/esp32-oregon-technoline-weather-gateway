"""CI/static checks for the late LILYGO stability overlay.
Run after PlatformIO pre-build source transformations.
"""
from pathlib import Path
root=Path(__file__).resolve().parent.parent
r=(root/'src/remote_access.cpp').read_text()
m=(root/'src/mb_compatible_publisher.cpp').read_text()
w=(root/'src/web_manager.cpp').read_text()
main=(root/'src/main.cpp').read_text()
conf=(root/'platformio.ini').read_text()
checks={
    'TLS V1 arbitration': 'MB_TLS_MEMORY_ARBITRATION_V1' in m,
    'Remote runtime V2': 'ADMIN_SENSOR_RUNTIME_V2' in r,
    'Segmented /api/state': 'ADMIN_SENSOR_STATE_SEGMENTED_V1' in r,
    'WSS direct reconnect': 'EXTERNAL_TLS_DIRECT_RECONNECT' in r,
    'Remote task deferral': 'LILYGO_STABILITY_REMOTE_LAZY_V1' in r and 'if(!cfg.portalUrl.isEmpty())startRemoteTasks();' in r,
    'Remote Web enablement': 'if(!u.isEmpty())startRemoteTasks()' in r,
    'MB worker deferral': 'LILYGO_STABILITY_MB_LAZY_V1' in m,
    'MB worker on-demand': 'if(!gWorkerTask && (cfg.enabled || gForceTest))' in m,
    'Low heap HTTPS guard': ('LILYGO_STABILITY_TLS_GUARD_V1' in m and
                            'blockAfterPause < MB_TLS_HEAP_PAUSE_THRESHOLD' in m and
                            'remoteAccessResumeAfterExternalTls();' in m and
                            'gBusy = false;' in m),
    'Web heap/stack metrics': 'heap_largest_block' in w and 'loop_stack_min_free_bytes' in w,
    'Boot reset reason': 'LILYGO_STABILITY_BOOT_DIAG_V1' in main,
    'V2 pre script registered': 'pre:scripts/apply_remote_runtime_v2.py' in conf,
    'Late patch registered': 'pre:scripts/apply_gateway_stability.py' in conf,
}
for k,v in checks.items():print(('PASS' if v else 'FAIL'),k)
assert all(checks.values()),'LILYGO stability integration incomplete'
