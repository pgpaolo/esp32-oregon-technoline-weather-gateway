Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
d = path.read_text(encoding="utf-8")

# A previous build may already have the final serialized remote startup block
# injected by apply_remote_state_fastpath.py. generate_web_ui.py intentionally
# runs Runtime V2 first, then the state fastpath. Restore Runtime V2's canonical
# startup block before that chain so both passes can re-apply cleanly on the
# same source archive/workspace.
boot = '''/* ADMIN_SENSOR_REMOTE_BOOT_SERIAL_V1 */
if(remoteUi){
 safeRefresh(true).finally(()=>{
  setTimeout(()=>safeLightning(true),1500);
  setTimeout(()=>safeMqtt(true),3500);
 });
}else{safeRefresh(true);safeLightning(true);safeMqtt(true);}'''
canonical = '''safeRefresh(true);
if(remoteUi){setTimeout(()=>safeLightning(true),2500);setTimeout(()=>safeMqtt(true),5000);}else{safeLightning(true);safeMqtt(true);}'''

if boot in d:
    d = d.replace(boot, canonical, 1)
    path.write_text(d, encoding="utf-8")
    print("Remote repeat-build repair: serialized startup restored to Runtime V2 anchor")
elif "ADMIN_SENSOR_REMOTE_BOOT_SERIAL_V1" in d:
    raise RuntimeError("Remote repeat-build repair: boot marker present but block shape changed")
else:
    print("Remote repeat-build repair: no serialized startup to restore")
