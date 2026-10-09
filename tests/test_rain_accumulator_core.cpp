#include "../src/rain_accumulator_core.h"
#include <cassert>
#include <iostream>
int main() {
 RainBucket o{}, t{};
 assert(accumulateRain(o, 1, 10000, 20261009, 202610, 2026).changed);
 assert(o.baselineValid && o.dayMilli == 0);
 assert(!accumulateRain(o, 1, 10000, 20261009, 202610, 2026).incremented);
 assert(accumulateRain(o, 1, 10254, 20261009, 202610, 2026).incremented);
 assert(o.dayMilli == 254 && o.monthMilli == 254 && o.lifetimeMilli == 254);
 assert(accumulateRain(o, 1, 11000, 20261010, 202610, 2026).incremented);
 assert(o.dayMilli == 746 && o.monthMilli == 1000 && o.yearMilli == 1000);
 accumulateRain(o, 1, 11500, 20261101, 202611, 2026);
 assert(o.monthMilli == 500 && o.yearMilli == 1500);
 accumulateRain(o, 1, 12000, 20270101, 202701, 2027);
 assert(o.dayMilli == 500 && o.yearMilli == 500 && o.lifetimeMilli == 2000);
 assert(accumulateRain(o, 1, 0, 20270101, 202701, 2027).rebased);
 assert(o.lifetimeMilli == 2000);
 accumulateRain(o, 1, 100, 20270101, 202701, 2027);
 assert(o.dayMilli == 600 && o.lifetimeMilli == 2100);
 assert(accumulateRain(o, 2, 14000, 20270101, 202701, 2027).rebased);
 assert(o.lifetimeMilli == 2100);
 assert(accumulateRain(o, 2, 514001, 20270101, 202701, 2027).rebased);
 assert(o.lifetimeMilli == 2100);
 accumulateRain(t, 22, 5000, 0, 0, 0);
 accumulateRain(t, 22, 5050, 0, 0, 0);
 assert(t.lifetimeMilli == 50 && t.dayMilli == 0);
 accumulateRain(t, 22, 5100, 20270101, 202701, 2027);
 assert(t.dayMilli == 50 && t.lifetimeMilli == 100);
 uint32_t daily = 999;
 assert(rainDailyMilli(o, true, 20270101, daily) && daily == 600);
 assert(rainDailyMilli(t, true, 20270101, daily) && daily == 50);
 // No fresh RF message is needed to keep the accumulated day available.
 assert(rainDailyMilli(t, true, 20270101, daily) && daily == 50);
 assert(!rainDailyMilli(t, false, 20270101, daily));
 assert(!rainDailyMilli(RainBucket{}, true, 20270101, daily));
 assert(!rainDailyMilli(t, true, 0, daily));
 assert(!rainDailyMilli(t, true, 20261231, daily));
 assert(rainDailyMilli(t, true, 20270102, daily) && daily == 0);
 assert(t.dayMilli == 50); // read does not mutate persistence state
 assert(sizeof(RainBucket) <= 64);
 std::cout << "PASS: rainfall core scenarios (duplicates/day/month/year/reset/replacement/outlier/no-NTP); bucket=" << sizeof(RainBucket) << " B\n";
}
