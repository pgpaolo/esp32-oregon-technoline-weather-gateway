Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
p = root / "src/sd_logger.cpp"
text = p.read_text(encoding="utf-8")

# apply_sd_format_tools.py upgrades an already-patched workspace in-place, but a
# clean checkout also needs the erase helper explicitly. Keep this guard tiny
# and idempotent so both first and repeated PlatformIO builds behave the same.
if "bool clearSdTree(const char *path) {" not in text:
    helper = r'''bool clearSdTree(const char *path) {
    while (true) {
        File dir = SD.open(path);
        if (!dir || !dir.isDirectory()) {
            if (dir) dir.close();
            return false;
        }
        File entry = dir.openNextFile();
        if (!entry) {
            dir.close();
            return true;
        }
        const String child = entry.path();
        const bool isDir = entry.isDirectory();
        entry.close();
        dir.close();
        if (isDir) {
            if (!clearSdTree(child.c_str()) || !SD.rmdir(child)) return false;
        } else if (!SD.remove(child)) {
            return false;
        }
        delay(0);
    }
}

'''
    anchor = "} // namespace\n\nvoid initSdLogger() {\n"
    if anchor not in text:
        raise RuntimeError("SD clear-tree guard: namespace anchor missing")
    p.write_text(text.replace(anchor, helper + anchor, 1), encoding="utf-8")
    print("SD clear-tree guard: restored helper")
