# Copyright 2023 The Pgx Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import jax
import jax.numpy as jnp

import pgx.v1 as v1
from pgx._src.struct import dataclass

FALSE = jnp.bool_(False)
TRUE = jnp.bool_(True)
CALL = jnp.int8(0)
BET = jnp.int8(1)
FOLD = jnp.int8(2)
CHECK = jnp.int8(3)


@dataclass
class State(v1.State):
    current_player: jnp.ndarray = jnp.int8(0)
    observation: jnp.ndarray = jnp.zeros((8, 8, 2), dtype=jnp.bool_)
    rewards: jnp.ndarray = jnp.float32([0.0, 0.0])
    terminated: jnp.ndarray = FALSE
    truncated: jnp.ndarray = FALSE
    legal_action_mask: jnp.ndarray = jnp.ones(4, dtype=jnp.bool_)
    _rng_key: jax.random.KeyArray = jax.random.PRNGKey(0)
    _step_count: jnp.ndarray = jnp.int32(0)
    # --- Kuhn poker specific ---
    _cards: jnp.ndarray = jnp.int8([-1, -1])
    # [(player 0),(player 1)]
    _last_action: jnp.ndarray = jnp.int8(-1)
    # 0(Call)  1(Bet)  2(Fold)  3(Check)
    _pot: jnp.ndarray = jnp.int8([0, 0])

    @property
    def env_id(self) -> v1.EnvId:
        return "kuhn_poker"


class KuhnPoker(v1.Env):
    def __init__(self):
        super().__init__()

    def _init(self, key: jax.random.KeyArray) -> State:
        return _init(key)

    def _step(self, state: v1.State, action: jnp.ndarray) -> State:
        assert isinstance(state, State)
        return _step(state, action)

    def _observe(self, state: v1.State, player_id: jnp.ndarray) -> jnp.ndarray:
        assert isinstance(state, State)
        return _observe(state, player_id)

    @property
    def id(self) -> v1.EnvId:
        return "kuhn_poker"

    @property
    def version(self) -> str:
        return "v0"

    @property
    def num_players(self) -> int:
        return 2


def _init(rng: jax.random.KeyArray) -> State:
    rng1, rng2 = jax.random.split(rng)
    current_player = jnp.int8(jax.random.bernoulli(rng1))
    init_card = jax.random.choice(
        rng2, jnp.int8([[0, 1], [0, 2], [1, 0], [1, 2], [2, 0], [2, 1]])
    )
    return State(  # type:ignore
        current_player=current_player,
        _cards=init_card,
        legal_action_mask=jnp.bool_([0, 1, 0, 1]),
    )


def _step(state: State, action):
    action = jnp.int8(action)
    pot = jax.lax.cond(
        (action == BET) | (action == CALL),
        lambda: state._pot.at[state.current_player].add(1),
        lambda: state._pot,
    )

    terminated, reward = jax.lax.cond(
        action == FOLD,
        lambda: (
            TRUE,
            jnp.float32([-1, -1]).at[1 - state.current_player].set(1),
        ),
        lambda: (FALSE, jnp.float32([0, 0])),
    )
    terminated, reward = jax.lax.cond(
        (state._last_action == BET) & (action == CALL),
        lambda: (TRUE, _get_unit_reward(state) * 2),
        lambda: (terminated, reward),
    )
    terminated, reward = jax.lax.cond(
        (state._last_action == CHECK) & (action == CHECK),
        lambda: (TRUE, _get_unit_reward(state)),
        lambda: (terminated, reward),
    )

    legal_action = jax.lax.switch(
        action,
        [
            lambda: jnp.bool_([0, 0, 0, 0]),  # CALL
            lambda: jnp.bool_([1, 0, 1, 0]),  # BET
            lambda: jnp.bool_([0, 0, 0, 0]),  # FOLD
            lambda: jnp.bool_([0, 1, 0, 1]),  # CHECK
        ],
    )

    return state.replace(  # type:ignore
        current_player=1 - state.current_player,
        _last_action=action,
        legal_action_mask=legal_action,
        terminated=terminated,
        rewards=reward,
        _pot=pot,
    )


def _get_unit_reward(state: State):
    return jax.lax.cond(
        state._cards[state.current_player]
        > state._cards[1 - state.current_player],
        lambda: jnp.float32([-1, -1]).at[state.current_player].set(1),
        lambda: jnp.float32([-1, -1]).at[1 - state.current_player].set(1),
    )


def _observe(state: State, player_id) -> jnp.ndarray:
    """
    Index   Meaning
    0~2     J ~ K in hand
    3~4     0~1 chips for the current player
    5~6     0~1 chips for the opponent
    """
    obs = jnp.zeros(7, dtype=jnp.bool_)
    obs = obs.at[state._cards[player_id]].set(TRUE)
    obs = obs.at[3 + state._pot[player_id]].set(TRUE)
    obs = obs.at[5 + state._pot[1 - player_id]].set(TRUE)

    return obs
