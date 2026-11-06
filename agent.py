"""A simple daily routine for every villager in Days at Three Branches."""

from __future__ import annotations

import heapq
from collections.abc import Mapping

from sandbox.observation_types import ThreeBranchesAction, ThreeBranchesObservation
from sandbox.village import action, day, geometry, layout, me, people, props

_TASK_STATES = {
    "stall": "closed",
    "bench": "empty",
    "shrine": "untended",
    "board": "none",
    "plot": "overgrown",
    "hearth": "unlit",
    "repair_bench": "idle",
    "pump": "idle",
    "bell": "silent",
}
_TOGGLE_TASKS = {"stall", "hearth"}
_LIGHTS = {"lantern", "hearth"}


class Agent:
    """Choose short village tasks by day and return home to sleep at night."""

    def reset(self, seed: int, observation: ThreeBranchesObservation) -> None:
        self._rng = me.rng(observation, seed)
        self._task: Mapping[str, object] | None = None
        self._task_started = False
        self._task_remaining = 0
        self._toggle_used = False
        self._completed_tasks: set[str] = set()
        self._wander_remaining = 0
        self._sweeping = False
        self._wander_heading = me.heading(observation)
        self._wave_cooldown = 0
        self._route_target: tuple[int, int] | None = None
        self._route: list[tuple[int, int]] = []
        self._route_index = 0

    def act(self, observation: ThreeBranchesObservation) -> ThreeBranchesAction:
        heading = me.heading(observation)
        wave = self._should_wave(observation)

        if day.phase(observation) == "night" or (
            day.phase(observation) == "evening" and day.tick(observation) >= 840
        ):
            self._task = None
            self._task_started = False
            return self._night_action(observation, heading, wave)

        if self._task is not None and not self._task_started:
            expected_state = _TASK_STATES[str(self._task["type"])]
            state = props.state(observation, str(self._task["id"]))
            if state is not None and state != expected_state:
                self._task = None

        if self._task is None:
            self._task = self._choose_task(observation)
            self._task_started = False
            self._toggle_used = False
            if self._task is not None:
                self._task_remaining = self._rng.randint(10, 15)
                self._wander_remaining = 0
                self._sweeping = False

        if self._task is None:
            return self._fallback_action(heading, wave)

        target = layout.cell_center(observation, self._task["cell"])
        destination = layout.nearest_walkable(observation, target)
        if destination is None:
            self._task = None
            return self._fallback_action(heading, wave)
        destination = layout.cell_center(observation, destination)
        usable = props.usable(observation)
        if usable is None or usable["id"] != self._task["id"]:
            return self._walk_to(
                observation, destination, 0.75, "wave" if wave else "none"
            )

        if wave:
            return action.stand(heading, "wave")

        self._task_started = True
        if self._task["type"] in _TOGGLE_TASKS:
            expression = "use" if not self._toggle_used else "none"
            self._toggle_used = True
        else:
            expression = "use"
        self._task_remaining -= 1
        if self._task_remaining <= 0:
            self._completed_tasks.add(str(self._task["id"]))
            self._task = None
            self._task_started = False
        return action.stand(heading, expression)

    def _choose_task(
        self, observation: ThreeBranchesObservation
    ) -> Mapping[str, object] | None:
        available = []
        for prop in props.all(observation):
            if str(prop["id"]) in self._completed_tasks:
                continue
            expected_state = _TASK_STATES.get(str(prop["type"]))
            if expected_state is None:
                continue
            state = props.state(observation, str(prop["id"]))
            if state is not None and state != expected_state:
                continue
            target = layout.cell_center(observation, prop["cell"])
            if layout.nearest_walkable(observation, target) is not None:
                available.append(prop)
        return self._rng.choice(available) if available else None

    def _fallback_action(self, heading: float, wave: bool) -> ThreeBranchesAction:
        if not self._sweeping:
            if self._wander_remaining <= 0:
                self._wander_remaining = self._rng.randint(10, 15)
                self._wander_heading = self._rng.uniform(0.0, 360.0)
            self._wander_remaining -= 1
            if self._wander_remaining == 0:
                self._sweeping = True
            return action.walk(
                self._wander_heading, 0.55, "wave" if wave else "none"
            )
        return action.walk(heading, 0.3, "wave" if wave else "sweep")

    def _night_action(
        self,
        observation: ThreeBranchesObservation,
        heading: float,
        wave: bool,
    ) -> ThreeBranchesAction:
        usable = props.usable(observation)
        if usable is not None and usable["type"] in _LIGHTS:
            state = props.state(observation, str(usable["id"]))
            if state == "unlit":
                target = layout.cell_center(observation, usable["cell"])
                return action.stand(
                    geometry.heading_to(me.position(observation), target), "use"
                )
            if state is None:
                target = layout.cell_center(observation, usable["cell"])
                return action.stand(
                    geometry.heading_to(me.position(observation), target),
                    "wave" if wave else "none",
                )

        home = me.home(observation)
        if home == "none":
            return action.stand(heading, "wave" if wave else "sleep")

        destination = self._sleep_spot(observation, home)
        if (
            layout.building_at(observation, me.position(observation)) == home
            and geometry.distance(me.position(observation), destination) <= 0.75
        ):
            return action.stand(heading, "wave" if wave else "sleep")
        return self._walk_to(observation, destination, 1.0, "wave" if wave else "none")

    @staticmethod
    def _sleep_spot(
        observation: ThreeBranchesObservation, home: str
    ) -> Mapping[str, object]:
        center = layout.building_center(observation, home)
        if center is None:
            doorway = layout.doorway(observation, home)
            return doorway if doorway is not None else me.position(observation)
        occupants = sorted(
            (
                str(person["id"])
                for person in people.roster(observation)
                if person["home"] == home
            ),
            key=lambda player_id: int(player_id.rsplit("_", 1)[-1]),
        )
        slot = occupants.index(me.player_id(observation)) if me.player_id(observation) in occupants else 0
        offset = -1.5 if slot == 0 else 1.5
        doorway = layout.doorway(observation, home)
        if doorway is not None and abs(doorway["x"] - center["x"]) > abs(doorway["y"] - center["y"]):
            return {"x": center["x"], "y": float(center["y"]) + offset}
        return {"x": float(center["x"]) + offset, "y": center["y"]}

    def _walk_to(
        self,
        observation: ThreeBranchesObservation,
        destination: Mapping[str, object],
        speed: float,
        expression: str,
    ) -> ThreeBranchesAction:
        target = layout.nearest_walkable(observation, destination)
        position = me.position(observation)
        if target is None:
            return action.walk(
                geometry.heading_to(position, destination), speed, expression
            )

        target_key = (int(target["x"]), int(target["y"]))
        current = layout.cell_at(observation, position)
        if current is None or not layout.walkable(observation, current):
            current = layout.nearest_walkable(observation, position)
        if current is None:
            return action.walk(
                geometry.heading_to(position, destination), speed, expression
            )
        current_key = (int(current["x"]), int(current["y"]))

        if self._route_target != target_key or not self._route:
            self._route = self._find_route(observation, current_key, target_key)
            self._route_target = target_key
            self._route_index = 0

        if self._route:
            route_index = next(
                (
                    index
                    for index in range(self._route_index, len(self._route))
                    if self._route[index] == current_key
                ),
                None,
            )
            if route_index is None:
                self._route = self._find_route(observation, current_key, target_key)
                self._route_index = 0
            else:
                self._route_index = route_index

        if self._route:
            waypoint_index = min(self._route_index + 1, len(self._route) - 1)
            waypoint = layout.cell_center(
                observation,
                {"x": self._route[waypoint_index][0], "y": self._route[waypoint_index][1]},
            )
            if waypoint_index == self._route_index == len(self._route) - 1:
                waypoint = destination
        else:
            waypoint = destination
        return action.walk(geometry.heading_to(position, waypoint), speed, expression)

    @staticmethod
    def _find_route(
        observation: ThreeBranchesObservation,
        start: tuple[int, int],
        target: tuple[int, int],
    ) -> list[tuple[int, int]]:
        frontier = [(abs(start[0] - target[0]) + abs(start[1] - target[1]), 0, start)]
        costs = {start: 0}
        previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while frontier:
            _, cost, current = heapq.heappop(frontier)
            if current == target:
                break
            if cost != costs[current]:
                continue
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                neighbor = (current[0] + dx, current[1] + dy)
                next_cost = cost + 1
                if next_cost >= costs.get(neighbor, float("inf")):
                    continue
                if not layout.can_step(
                    observation,
                    {"x": current[0], "y": current[1]},
                    {"x": neighbor[0], "y": neighbor[1]},
                ):
                    continue
                costs[neighbor] = next_cost
                previous[neighbor] = current
                priority = next_cost + abs(neighbor[0] - target[0]) + abs(neighbor[1] - target[1])
                heapq.heappush(frontier, (priority, next_cost, neighbor))

        if target not in previous:
            return []
        route = [target]
        while route[-1] != start:
            parent = previous[route[-1]]
            if parent is None:
                return []
            route.append(parent)
        route.reverse()
        return route

    def _should_wave(self, observation: ThreeBranchesObservation) -> bool:
        if self._wave_cooldown > 0:
            self._wave_cooldown -= 1
            return False
        nearby_passers = any(
            geometry.distance(me.position(observation), person["position"]) <= 4.0
            for person in people.nearby(observation)
        )
        if people.seen(observation) or nearby_passers:
            self._wave_cooldown = 8
            return True
        return False
