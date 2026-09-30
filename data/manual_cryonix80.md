# Cryonix 80 Ultra-Low Freezer — Service Manual (excerpt)

Fictional manual for the demo. Each section starts with its id; the `search_manuals` skill returns whole sections, and the agent cites them by id.

## MAN-CX80-NORMAL — Normal operating values

Use these values to judge the daily telemetry summary.

| Reading | Normal |
|---|---|
| Cabinet temperature (daily average) | −80 °C ± 1 |
| Compressor duty cycle | 50–65 % |
| Compressor current | 3.8–4.8 A |
| Recovery to setpoint after the door closes | about 15 min |
| Condenser temperature | 35–42 °C |

Revision is set by serial number: **serial below 5000 = revision A**, **5000 and above = revision B**.

## MAN-CX80-E21 — E-21 Condenser temperature high

**Raised when** the condenser is above 48 °C.

**Most likely cause:** clogged condenser air filter. The condenser cannot release heat into the room. Common near autoclaves or in dusty rooms.

1. Check the air filter at the front bottom grille.
2. If dusty, replace it with **AirFilter 80 (AF-80)**. Fits both revisions.
3. Condenser temperature should return below 42 °C within a day.

The cabinet usually stays colder than −77 °C (no E-47); this is not yet a sample risk.

## MAN-CX80-E31 — E-31 Door ajar

**Raised when** the door stays open longer than 10 minutes.

**Most likely cause:** the door was not closed properly. No part is needed.

1. Confirm the door closes and latches.
2. Remind users to close and latch the door.
3. Only if the latch is damaged, book a visit.

## MAN-CX80-E47 — E-47 Temperature creep

**Raised when** the daily average cabinet temperature is above −77 °C.

**Two possible causes.** Use the telemetry to tell them apart. **The deciding sign is compressor current**: a badly worn gasket can also recover very slowly, but its current stays normal.

| Sign | Worn door gasket | Failing compressor |
|---|---|---|
| Temperature | Rises slowly over days | Rises, cannot return to −80 °C even with the door closed |
| Recovery after door closes | Slow (above 30 min) | Very slow (60 min or more) |
| Compressor current | **Normal** (3.8–4.8 A) | **5 A or more, and rising** |
| Duty cycle | High (70–90 %) | Almost always on (95 % or more) |
| Other | Frost or ice on the door seal | — |

**Recently replaced parts:** a part replaced in the last **90 days** is unlikely to be the cause. Look at the other cause first.

**No telemetry:** do not diagnose from the alarm alone and do not order parts. Sample risk is unknown: ask the customer to read the temperature on the display. Ask them to restore the connection or run remote diagnostics, and escalate to Technical Support.

Then follow MAN-CX80-GASKET or MAN-CX80-COMPRESSOR, and check MAN-CX80-SAMPLES.

## MAN-CX80-GASKET — Door gasket replacement

The gasket kit is **specific to the revision**. The kits look identical but do not fit the other revision.

| Revision | Serials | Kit |
|---|---|---|
| A | below 5000 | **GasketKit 80-A (GK-80-A)** |
| B | 5000 and above | **GasketKit 80-B (GK-80-B)** |

1. Warm the new gasket to room temperature for 1 hour.
2. Remove the old gasket; clean the door channel.
3. Fit the new gasket; check the seal with a paper strip at 8 points.
4. Recovery after door close should return to about 15 min within 24 hours.

Typical visit: 2 hours. Samples can stay inside if the door is kept closed.

## MAN-CX80-COMPRESSOR — Compressor replacement

Part: **Compressor CX (CMP-CX)**. Fits both revisions. Field engineers only.

1. Move all samples to a backup freezer first (see MAN-CX80-SAMPLES).
2. Recover refrigerant, replace the compressor, recharge.
3. Allow 12 hours to pull down to −80 °C before returning samples.

Typical visit: 1 day.

## MAN-CX80-SAMPLES — Samples at risk

If the cabinet is **warmer than −70 °C**, samples are at risk.

1. Treat the visit as **urgent**.
2. Advise the customer to move samples to a backup freezer now.
3. Do not wait for the parts to arrive before moving samples.

If the cabinet is **−70 °C or colder**, samples are not yet at risk: the visit is **routine**, within the contract's service time.
