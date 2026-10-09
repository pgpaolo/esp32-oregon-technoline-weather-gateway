# Proposed mixed licensing — decoder GPL, original work PolyForm / Schema proposto

**Status: DRAFT FOR FUTURE EDITION — NOT AN OPERATIVE LICENSE / BOZZA NON OPERATIVA.**

**Requested policy / Obiettivo:** retain the original license of each third-party decoder and library; seek **PolyForm Noncommercial 1.0.0** for the author's independently copyrightable original contributions, with separate written authorization for commercial exploitation of those contributions.

**Current repository status:** the existing whole-firmware distribution remains **GNU GPL-3.0-or-later**. Its `LICENSE`, `NOTICE`, releases and pre-existing author grants must not be silently overwritten.

## 1. What the proposed rule covers

| Class / Classe | Intended approach / Approccio | Present release status |
|---|---|---|
| Technoline / La Crosse decoder `src/lacrosse_ws23xx.cpp` | Preserve the applicable GPL terms and all third-party notices until provenance is fully resolved. | GPL notices present; no PolyForm relicensing authorized. |
| Other decoders | Preserve any upstream third-party license; verify file-level provenance first (Oregon is **not automatically considered third-party GPL**). | Case-by-case review pending. |
| MIT / BSD libraries | Their upstream license continues; preserve copyrights, conditions and disclaimers. | Permissive terms remain unaffected. |
| LGPL libraries (notably WebSockets and AS3935MI) | Preserve upstream LGPL and fulfill firmware/static-link distribution obligations. | Exact binary and license compliance still under review. |
| Original architecture, UI, integration, telemetry, documentation | May be offered under a separate PolyForm noncommercial license **only where rights and legal separability are established**, in a future legally compliant edition. | Existing GPL license grants remain valid. |
| One combined executable on ESP32 | **Cannot be declared wholly PolyForm Noncommercial while incorporating GPL-covered third-party derived program code without additional permission or an appropriate GPL-compatible redesign.** | GPL applies to the existing release; proposed whole-program restriction is **BLOCKED**. |

## 2. Why file-by-file labels are not enough

The current gateway compiles the Technoline/La Crosse implementation into the **same firmware image** as the main program:
- `src/main.cpp` includes `lacrosse_ws23xx.h`, calls `initLaCrosseWs23xx()`, `getLaCrossePacket()` and `parseLaCrossePacket()`;
- `src/oregon_receiver.cpp` includes that header and calls Technoline processing from the shared SX1278 radio pipeline;
- `platformio.ini` produces integrated `t3-v161-433` / `t3-s3-433` firmware images, not independent executables.

This is **integration**, not merely separate GPL software shipped next to independent noncommercial software. If copyrightable GPL code has been adapted from PracticalArduino/rtl_433, the redistribution of the complete program cannot acquire additional noncommercial restrictions without upstream consent. Copyright on an *independent, original portion* and license permission for the *combined distributed program* are different questions.

**Do not mislabel the existing tree as `PolyForm-Noncommercial-1.0.0` at its root or put blanket noncommercial notices in its source files.** That would risk incorrectly claiming rights over GPL-covered contributions. Merely putting the decoder into another folder or static library does **not** establish legal independence.

Authoritative references:
- GNU GPL FAQ: https://www.gnu.org/licenses/gpl-faq.en.html#GPLInProprietarySystem
- GNU GPL compatibility: https://www.gnu.org/licenses/gpl-faq.en.html#WhatDoesCompatMean
- PolyForm Noncommercial official terms: https://polyformproject.org/licenses/noncommercial/1.0.0

## 3. Permitted paths to the requested arrangement / Strade possibili

**A — Additional permission from the actual upstream rightsholders.**
Identify all actual copied/derived expression in Technoline decoding and request explicit written authority allowing its inclusion in the specific noncommercial/proprietary overall firmware edition and, if desired, separate commercial licensing. Mere GPL publication is **not** such an authorization. Preserve the obligations of LGPL and other third-party components.

**B — Documented independent replacement.**
Develop an independent decoder based on technical protocol facts and original RF traces rather than copying/adapting source expressions. Confirm the provenance of every remaining component and its license. Validate RF, SPI, memory, Web, MQTT, rainfall and 24-hour physical stability before using it. Only then consider a PolyForm edition of the work whose owners grant that license.

**C — Truly separate works rather than one ESP32 image.**
An external/independent GPL decoder program and a distinct noncommercial app could sometimes be distributed side by side under different licenses, provided they remain genuinely separate programs. Evaluate technical coupling, semantics, IPC and implementation with legal review. The **current single ESP32 image does not satisfy this arrangement**, and extracting a decoder is a material engineering change with reliability risk.

**D — Keep the existing combined product GPL.**
Preserve compatibility and offer paid support, customization, integration and testing, while retaining copyright and attribution. This **does not ban third-party commercial use** under the existing GPL.

## 4. Why old GPL versions remain available

Previously published GPL editions and any copies legitimately obtained under those terms retain their grant. A copyright holder can make a **new additional offering** of exclusively controlled original code under separate terms, but the new offering does not withdraw previous GPL rights or transform third-party GPL code into PolyForm. A dual-license notice on parts already under GPL also **does not stop** use of those parts through the pre-existing GPL route.

## 5. Future documentation model — gated, not operative

Only after upstream permissions / independent replacement and title review:

```text
NEW EDITION ROOT/
  LICENSE                       -> official PolyForm Noncommercial 1.0.0, if entire edition legally qualifies
  NOTICE                        -> copyright and detailed third-party attributions
  LICENSES/                     -> unmodified exact GPL/LGPL/MIT/BSD license texts where required
  docs/THIRD_PARTY_NOTICES.md   -> dependency versions and license obligations
  src/                           -> per-file SPDX, only after ownership/license verification
```

Even in a future edition, GPL code that remains *combined in one covered program* cannot be treated as an automatic exception just by listing its license in `LICENSES/`. Get an explicit exception or replace the GPL-derived portion first. `PolyForm Noncommercial` also expressly permits use by government institutions, charities, and educational/public-research organizations; it is not a blanket ban on all organizational activity.

## 6. No firmware changes and release gate

**DO NOT** modify `src/`, `platformio.ini`, CI builds, decoders or UI to implement this license proposal. All decisions are documentation-only until the provenance and license gates in [NONCOMMERCIAL_MIGRATION_PLAN.md](NONCOMMERCIAL_MIGRATION_PLAN.md) pass.

**Present decision:** GPL remains authoritative for the existing integrated firmware; whole-product PolyForm is **not yet lawful/verified**, and commercial restrictions must not be asserted as already effective.

This is a preliminary engineering/legal provenance analysis, not a legal opinion.
