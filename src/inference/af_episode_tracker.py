from dataclasses import dataclass, field


@dataclass
class AFEpisodeTracker:
    window_seconds: float = 30.0
    afib_probability_threshold: float = 0.7
    min_consecutive_windows: int = 2
    decision_mode: str = "argmax_and_threshold"
    total_windows: int = 0
    af_episode_count: int = 0
    total_af_duration_sec: float = 0.0
    longest_af_episode_sec: float = 0.0
    active: bool = False
    current_episode_duration_sec: float = 0.0
    _consecutive_afib_windows: int = 0
    _pending_duration_sec: float = 0.0
    history: list = field(default_factory=list)

    def update(self, rhythm_label, possible_afib_probability=0.0):
        self.total_windows += 1
        probability_passed = float(possible_afib_probability) >= self.afib_probability_threshold
        if self.decision_mode == "probability_only":
            is_afib_window = probability_passed
        else:
            is_afib_window = rhythm_label == "possible_afib" and probability_passed

        if is_afib_window:
            self._consecutive_afib_windows += 1
            if not self.active:
                self._pending_duration_sec += self.window_seconds
                if self._consecutive_afib_windows >= self.min_consecutive_windows:
                    self.active = True
                    self.af_episode_count += 1
                    self.current_episode_duration_sec = self._pending_duration_sec
                    self.total_af_duration_sec += self._pending_duration_sec
                    self.longest_af_episode_sec = max(
                        self.longest_af_episode_sec,
                        self.current_episode_duration_sec,
                    )
            else:
                self.current_episode_duration_sec += self.window_seconds
                self.total_af_duration_sec += self.window_seconds
                self.longest_af_episode_sec = max(
                    self.longest_af_episode_sec,
                    self.current_episode_duration_sec,
                )
        else:
            self._consecutive_afib_windows = 0
            self._pending_duration_sec = 0.0
            self.active = False
            self.current_episode_duration_sec = 0.0

        summary = self.summary()
        self.history.append(
            {
                "rhythm_label": rhythm_label,
                "possible_afib_probability": float(possible_afib_probability),
                "decision_mode": self.decision_mode,
                "afib_probability_threshold": float(self.afib_probability_threshold),
                **summary,
            }
        )
        return summary

    def summary(self):
        total_duration = max(self.total_windows * self.window_seconds, 1e-9)
        return {
            "active": bool(self.active),
            "current_episode_duration_sec": round(float(self.current_episode_duration_sec), 3),
            "af_episode_count": int(self.af_episode_count),
            "longest_af_episode_sec": round(float(self.longest_af_episode_sec), 3),
            "total_af_duration_sec": round(float(self.total_af_duration_sec), 3),
            "af_burden_percent": round(float(100.0 * self.total_af_duration_sec / total_duration), 3),
            "decision_mode": self.decision_mode,
            "afib_probability_threshold": float(self.afib_probability_threshold),
        }
