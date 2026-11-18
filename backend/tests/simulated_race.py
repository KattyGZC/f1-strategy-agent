"""A ten-lap race calibrated on two dry compounds, with round coefficients, so a strategy's
lap times can be written out by hand."""

from decimal import Decimal

from f1_strategy.domain.clean import Compound
from f1_strategy.domain.lap_time_model import Calibration, CompoundFit, DriverPace
from f1_strategy.domain.pit_loss import PitLoss
from f1_strategy.domain.strategy import StrategyStint

DRIVER = 1
# SOFT: 90 + 0.1 * age - 0.05 * (lap - 1); HARD: 91 + 0.05 * age - 0.05 * (lap - 1).
CALIBRATION = Calibration(
    race_laps=10,
    compounds=(
        CompoundFit(Compound.SOFT, Decimal(90), Decimal("0.1"), Decimal("-0.05"), Decimal("0.4"),
                    clean_laps=40, min_tyre_age_laps=1, max_tyre_age_laps=5),
        CompoundFit(Compound.HARD, Decimal(91), Decimal("0.05"), Decimal("-0.05"), Decimal("0.4"),
                    clean_laps=40, min_tyre_age_laps=1, max_tyre_age_laps=8),
    ),
    drivers=(DriverPace(DRIVER, Decimal("0.3"), 40), DriverPace(44, Decimal("-0.3"), 40)),
    residual_rmse_s=Decimal("0.4"),
    exclusions=(),
    track_temperature=None,
    rain_readings=0,
    pit_loss=PitLoss(Decimal("20.000"), stops=10),
    pit_stop_exclusions=(),
)  # fmt: skip
SOFT_THEN_HARD = (StrategyStint(Compound.SOFT, 4, 0), StrategyStint(Compound.HARD, 6, 0))
HARD_ONLY = (StrategyStint(Compound.HARD, 10, 0),)
