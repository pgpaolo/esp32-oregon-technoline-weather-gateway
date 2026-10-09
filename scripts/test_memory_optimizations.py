#!/usr/bin/env python3
"""Standalone source-backed host regression for classic ESP32 SRAM optimizations.

Python 3 + g++ only. The harness compiles the ACTUAL ISR/consumer functions
extracted from src/oregon_receiver.cpp against tiny Arduino/GPIO stubs, then
compares 200,000 randomized ring operations with the former (unpacked) model.
No ESP32 radio or PlatformIO toolchain is required for this host-only test.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
rf = (ROOT / "src/oregon_receiver.cpp").read_text(encoding="utf-8")
web = (ROOT / "src/web_manager.cpp").read_text(encoding="utf-8")


def cpp_function(src: str, marker: str) -> str:
    start = src.index(marker)
    opening = src.index("{", start)
    depth = 0
    for i in range(opening, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise RuntimeError("Unbalanced C++ function: " + marker)


assert "edgeLevelRing[EDGE_RING_SIZE]" not in rf
assert "edgeLevelBits[EDGE_RING_SIZE / 32U]" in rf
assert "e.sourceName" not in web and "e.protocol" not in web
assert "rawTypeName(e)" in web and "rawProtocolName(e)" in web
assert "rawSourceName(e)" in web

ring = rf[rf.index("constexpr uint16_t EDGE_RING_SIZE = 4096;"):rf.index("struct EdgeDecoder {")]
raw = web[web.index("struct RawEntry {"):web.index("RawEntry history[")]
isr = cpp_function(rf, "void IRAM_ATTR onDirectDataEdge()")
pop = cpp_function(rf, "bool popEdge(uint16_t &durationUs, uint8_t &level)")
raw_names = "\n".join(cpp_function(web, signature) for signature in (
    "const char *rawProtocolName(",
    "const char *rawSourceName(",
    "const char *rawTypeName(",
))

code = r'''
#include <cstdint>
#include <cstddef>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <random>
#include <utility>
#include <cassert>
#define IRAM_ATTR
#define RADIO_DIO2_PIN 26
using gpio_num_t = int;
static uint32_t mockMicros = 0;
static uint8_t mockPin = 1;
uint32_t micros() { return mockMicros; }
int gpio_get_level(gpio_num_t) { return mockPin; }
static constexpr size_t OREGON_MAX_PACKET_BYTES = 12;
enum class OregonDecodeSource : uint8_t { ClockSync, EdgeTiming, EdgeTimingWeak, EdgeTimingState, BurstAdaptive, EdgeTimingV21 };
enum class SensorType : uint8_t { Unknown, ThermoHygro, Wind, Rain, UV };
enum class LaCrosseType : uint8_t { Unknown, Temperature, Humidity, Rain, Wind, Gust };
const char *oregonDecodeSourceName(OregonDecodeSource s) {
    switch(s) { case OregonDecodeSource::ClockSync: return "clock";
      case OregonDecodeSource::EdgeTiming: return "edge";
      case OregonDecodeSource::EdgeTimingWeak: return "edge-weak";
      case OregonDecodeSource::EdgeTimingState: return "edge-state";
      case OregonDecodeSource::BurstAdaptive: return "burst-adapt";
      case OregonDecodeSource::EdgeTimingV21: return "edge-v2.1";
      default: return "unknown"; }
}
const char *sensorTypeName(SensorType s) { return s == SensorType::ThermoHygro ? "thermo_hygro" : "unknown"; }
const char *laCrosseTypeName(LaCrosseType s) { return s == LaCrosseType::Gust ? "gust" : "unknown"; }
''' + ring + "\n" + raw + "\n" + raw_names + "\n" + isr + "\n" + pop + r'''

// Previous-version struct, used only to compare static SRAM size.
struct PreviousRawEntry {
    uint32_t ms{0}; float rssi{NAN}; uint8_t len{0};
    uint8_t sensorId{0}; uint16_t sensorCode{0}; uint8_t source{0};
    char protocol[12]{}; char sourceName[16]{};
    bool accepted{false}; bool batteryKnown{false}; bool batteryLow{false};
    char type[16]{}; char decoded[128]{};
    char hex[OREGON_MAX_PACKET_BYTES * 3]{};
};

int main() {
    constexpr size_t count=4096;
    const size_t oldRF = count * (sizeof(uint16_t) + sizeof(uint8_t));
    const size_t newRF = sizeof(edgeDurationRing) + sizeof(edgeLevelBits);
    const size_t oldWeb = 32U * sizeof(PreviousRawEntry);
    const size_t newWeb = 32U * sizeof(RawEntry);
    assert(oldRF == 12288U && newRF == 8704U);
    assert(oldWeb > newWeb);
    RawEntry e{};
    assert(std::strcmp(rawProtocolName(e),"Oregon") == 0);
    assert(std::strcmp(rawTypeName(e),"rejected") == 0);
    e.typeCode=uint8_t(SensorType::ThermoHygro);
    e.source=uint8_t(OregonDecodeSource::EdgeTimingV21);
    assert(std::strcmp(rawTypeName(e),"thermo_hygro") == 0);
    assert(std::strcmp(rawSourceName(e),"edge-v2.1") == 0);
    e.technoline=true;
    e.typeCode=uint8_t(LaCrosseType::Gust);
    for(uint8_t src=0; src<3U; ++src) {
        e.source=src;
        assert(std::strcmp(rawProtocolName(e),"Technoline") == 0);
        assert(std::strcmp(rawTypeName(e),"gust") == 0);
        assert(std::strcmp(rawSourceName(e),src==1?"pwm-leader":src==2?"pwm-burst":"pwm-window") == 0);
    }
    std::printf("RAW metadata decoder regression PASS\n");
    std::printf("RF old=%zu new=%zu saved=%zu bytes\n", oldRF,newRF,oldRF-newRF);
    std::printf("RAW old=%zu new=%zu saved=%zu bytes\n", oldWeb,newWeb,oldWeb-newWeb);
    std::printf("TOTAL SRAM saved=%zu bytes\n",oldRF+oldWeb-newRF-newWeb);

    // Simulate ISR and foreground consumer, including empty/full queue and
    // rollover at 2^32 microseconds. Include intervals >65535 us (clamping).
    std::mt19937 gen(613726);
    std::deque<std::pair<uint16_t,uint8_t>> expected;
    mockMicros=0xFFFFFEF0U;
    mockPin=0;
    onDirectDataEdge(); // first edge is deliberately used to prime the decoder
    for (unsigned k=0; k<200000U; ++k) {
        if (expected.size() && (gen()%5U) < 2U) {
            uint16_t duration; uint8_t level;
            assert(popEdge(duration,level));
            auto want=expected.front(); expected.pop_front();
            if (duration!=want.first || level!=want.second) {
                std::fprintf(stderr,"mismatch at %u: got=%u/%u expected=%u/%u\n",k,duration,level,want.first,want.second);
                return 2;
            }
        } else {
            const uint32_t delta = 1U+(gen()%90000U);
            mockMicros += delta;
            mockPin = uint8_t(gen() & 1U);
            const auto sizeBefore=expected.size();
            onDirectDataEdge();
            if (sizeBefore < count-1U)
                expected.emplace_back(uint16_t(delta>65535U?65535U:delta),uint8_t(mockPin^1U));
        }
    }
    uint16_t d; uint8_t l;
    while(!expected.empty()) {
        assert(popEdge(d,l));
        auto want=expected.front(); expected.pop_front();
        assert(d==want.first && l==want.second);
    }
    assert(!popEdge(d,l));
    assert(isrOverflowCount>0U);
    std::printf("RF ring randomized 200000 operations PASS (overflows=%u)\n",(unsigned)isrOverflowCount);
    return 0;
}
'''

compiler = shutil.which("g++")
if not compiler:
    print("SKIPPED: g++ not installed; structural assertions PASS")
else:
    with tempfile.TemporaryDirectory(prefix="weather-memory-test-") as temp:
        source = Path(temp) / "memory_test.cpp"
        binary = Path(temp) / "memory_test"
        source.write_text(code, encoding="utf-8")
        subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-o", str(binary), str(source)], check=True)
        subprocess.run([str(binary)], check=True)
    print("Source-backed host regression PASS")
