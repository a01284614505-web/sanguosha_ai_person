const GameUI = {
    sel: null,
    hand: [],
    hero: null,
    myId: null,
    needTarget: false,
    pendingAction: null,
    availableActions: [],
    selectedLegalAction: null,
    targetSelection: [],
    gameConfig: {},
    playerName: '玩家',
    latestState: null,
    responseTimer: null,
    activeResponseRequest: null,
    cardAnimationQueue: Promise.resolve(),
    aiSettingProviderList: null
};
window.GameUI = GameUI;

try {
    GameUI.gameConfig = JSON.parse(localStorage.getItem('gameConfig') || '{}') || {};
} catch (e) {
    GameUI.gameConfig = {};
}
GameUI.playerName = GameUI.gameConfig.player_name || '玩家';

function configIsLegal(cfg) {
    return !!(cfg && cfg.selected_hero && cfg.selected_hero.id
        && Array.isArray(cfg.ais) && cfg.ais.length === 4);
}

function rejectBadConfig(message) {
    alert(message);
    location.href = 'index.html';
}

function heroImg(heroId, label) {
    var fallback = String(label || '?').charAt(0);
    if (!heroId) return fallback;
    return '<img src="assets/heroes/' + heroId + '.jpg" alt="' + String(label || '') +
        '" onerror="this.onerror=null;this.outerHTML=(this.alt||\'?\').charAt(0);">';
}

function L(m, isChat) {
    var l = document.getElementById('log'), d = document.createElement('div');
    d.className = isChat ? 'chat' : '';
    d.textContent = m;
    l.appendChild(d);
    l.scrollTop = l.scrollHeight;
    if (l.children.length > 50) l.removeChild(l.firstChild);
}

function getCardSourcePosition(data) {
    if (data.actor_id === GameUI.myId && Number.isInteger(data.card_index)) {
        var ownCard = document.getElementById('hand').children[data.card_index];
        if (ownCard) {
            var ownRect = ownCard.getBoundingClientRect();
            return {x: ownRect.left, y: ownRect.top};
        }
    }
    var actor = document.getElementById('opp_' + data.actor_id);
    if (actor) {
        var actorRect = actor.getBoundingClientRect();
        return {x: actorRect.left + actorRect.width / 2 - 30, y: actorRect.top + actorRect.height / 2 - 42};
    }
    return {x: window.innerWidth / 2 - 30, y: window.innerHeight / 2 - 42};
}

function enqueueCardAnimation(data) {
    GameUI.cardAnimationQueue = GameUI.cardAnimationQueue.then(function () {
        return animateCardToDiscard(data);
    }).catch(function (error) {
        console.error('卡牌动画失败:', error);
    });
}

function animateCardToDiscard(data) {
    return new Promise(function (resolve) {
        var card = data.card || {};
        var start = getCardSourcePosition(data);
        var fly = document.createElement('div');
        fly.className = 'flyingCard';
        var suitSym = {spade: '♠', heart: '♥', club: '♣', diamond: '♦'}[card.suit] || '?';
        var col = ['heart', 'diamond'].includes(card.suit) ? 'r' : 'b';
        fly.innerHTML = '<div class="cs ' + col + '">' + suitSym + (card.rank || '') + '</div><div class="cn">' + (card.name || data.card_name || '?') + '</div>';
        fly.style.left = start.x + 'px';
        fly.style.top = start.y + 'px';
        document.body.appendChild(fly);

        var animationMs = (window.getGlobalSettings ? getGlobalSettings().animation_ms : 1100);
        var centerPause = Math.round(animationMs * .59);
        var centerMove = Math.max(260, Math.round(animationMs * .35));
        var discardMove = Math.max(280, animationMs - centerPause);
        var centerX = window.innerWidth / 2 - 30;
        var centerY = Math.max(38, window.innerHeight * .29 - 42);
        var pileRect = document.getElementById('discardPile').getBoundingClientRect();
        var pileX = pileRect.left + pileRect.width / 2 - 30;
        var pileY = pileRect.top + pileRect.height / 2 - 42;

        requestAnimationFrame(function () {
            fly.style.transition = 'all ' + centerMove + 'ms cubic-bezier(.2,.8,.2,1)';
            fly.style.left = centerX + 'px';
            fly.style.top = centerY + 'px';
            fly.style.transform = 'scale(1.18)';
            fly.style.boxShadow = '0 0 28px rgba(212,175,55,.9)';
        });

        setTimeout(function () {
            fly.style.transition = 'all ' + discardMove + 'ms cubic-bezier(.4,0,.2,1)';
            fly.style.left = pileX + 'px';
            fly.style.top = pileY + 'px';
            fly.style.transform = 'scale(.78) rotate(10deg)';
            fly.style.opacity = '.82';
        }, centerPause);

        setTimeout(function () {
            if (fly.parentNode) fly.parentNode.removeChild(fly);
            showDiscardTop(card.name || data.card_name);
            if (Number.isInteger(data.discard_count)) {
                document.getElementById('discardCount').textContent = data.discard_count;
            }
            if (window.audioManager) audioManager.play('card');
            if (data.animation_id) {
                gameClient.send({type: Protocol.INBOUND.CARD_ANIMATION_DONE, animation_id: data.animation_id});
            }
            resolve();
        }, animationMs);
    });
}

function showDiscardTop(cardName) {
    if (!cardName) return;
    var top = document.getElementById('topCard');
    top.textContent = cardName;
    top.classList.add('show');
    setTimeout(function () { top.classList.remove('show'); }, 1200);
}

gameClient.onConnect = function () {
    L('已连接');
    if (!configIsLegal(GameUI.gameConfig)) {
        rejectBadConfig('对局配置不完整，请从大厅重新开始。');
        return;
    }
    var hero = GameUI.gameConfig.selected_hero;
    GameUI.hero = hero;
    GameUI.playerName = GameUI.gameConfig.player_name || '玩家';
    var deckId = GameUI.gameConfig.deck_id || localStorage.getItem('active_deck') || '';
    document.getElementById('myname').textContent = GameUI.playerName;
    document.getElementById('myav').innerHTML = heroImg(hero.id, hero.name || GameUI.playerName);
    document.getElementById('myhp').textContent = '❤️'.repeat(hero.max_hp || 4);

    GameUI.gameConfig.player = {name: GameUI.playerName, is_ai: false, hero: hero};
    if (deckId) GameUI.gameConfig.deck_id = deckId;
    // 清除上一局结算快照：中断或刷新后不得在结算页展示旧数据。
    localStorage.removeItem('gameResult');
    gameClient.createGame(GameUI.gameConfig);
};

gameClient.onRequireResponse = function (data) {
    GameUI.activeResponseRequest = data;
    GameUI.responseExpired = false;
    var modal = document.getElementById('responseModal');
    var options = document.getElementById('responseOptions');
    var multiSelect = document.getElementById('responseMultiSelect');
    var multiOptions = document.getElementById('responseMultiOptions');
    options.innerHTML = '';
    multiOptions.innerHTML = '';
    var titleMap = {
        dying: '濒死响应',
        wuxie: '无懈可击',
        choose_cards: '选择卡牌',
        choose_players: '选择角色',
        confirm: '请选择',
        choose_option: '请选择'
    };
    document.getElementById('responseTitle').textContent = titleMap[data.kind] || '场外响应';
    document.getElementById('responsePrompt').textContent = data.prompt || '请选择是否响应';
    document.getElementById('responseContext').textContent = data.requested_name ? '需要：' + data.requested_name : '';

    var sel = data.selection || {};
    var isMulti = sel.mode === 'multi';

    if (isMulti) {
        options.style.display = 'none';
        multiSelect.style.display = '';
        GameUI.multiSelected = [];
        var minN = sel.min != null ? Number(sel.min) : 1;
        var maxN = sel.max != null ? Number(sel.max) : 1;
        var confirmBtn = document.getElementById('responseMultiConfirm');
        function updateCount() {
            var n = GameUI.multiSelected.length;
            var hint = minN !== maxN ? '（至少 ' + minN + '）' : '';
            document.getElementById('responseMultiCount').textContent = '已选 ' + n + ' / ' + maxN + hint;
            confirmBtn.disabled = GameUI.responseExpired || n < minN || n > maxN;
        }
        (data.options || []).forEach(function (option, index) {
            var item = document.createElement('div');
            item.className = 'multi-select-item';
            item.textContent = option.label || (option.card && option.card.name) || String(index);
            item.dataset.index = index;
            item.onclick = function () {
                if (GameUI.responseExpired) return;
                var idx = GameUI.multiSelected.indexOf(index);
                if (idx === -1) {
                    if (GameUI.multiSelected.length < maxN) {
                        GameUI.multiSelected.push(index);
                        item.classList.add('selected');
                    }
                } else {
                    GameUI.multiSelected.splice(idx, 1);
                    item.classList.remove('selected');
                }
                updateCount();
            };
            multiOptions.appendChild(item);
        });
        updateCount();
    } else {
        options.style.display = '';
        multiSelect.style.display = 'none';
        (data.options || []).forEach(function (option, index) {
            var button = document.createElement('button');
            button.textContent = option.label || ((option.card && option.card.name) || '不响应');
            if (option.is_pass) button.className = 'pass';
            if (option.hidden) button.classList.add('hidden-card');
            button.onclick = function () { submitResponse(index); };
            options.appendChild(button);
        });
    }

    modal.classList.add('show');
    var left = Math.max(0, Number(data.timeout) || 30);
    var countdown = document.getElementById('responseCountdown');
    clearInterval(GameUI.responseTimer);
    function expireResponse() {
        GameUI.responseExpired = true;
        if (GameUI.activeResponseRequest) GameUI.activeResponseRequest.expired = true;
        countdown.textContent = '已超时，由托管代选';
        var confirmBtnEl = document.getElementById('responseMultiConfirm');
        if (confirmBtnEl) confirmBtnEl.disabled = true;
        options.querySelectorAll('button').forEach(function (btn) { btn.disabled = true; });
        setTimeout(function () {
            if (GameUI.responseExpired) modal.classList.remove('show');
        }, 800);
    }
    function tick() {
        if (GameUI.responseExpired) return;
        countdown.textContent = '剩余 ' + Math.max(0, left) + ' 秒';
        if (left <= 0) {
            clearInterval(GameUI.responseTimer);
            expireResponse();
            return;
        }
        left--;
    }
    tick();
    GameUI.responseTimer = setInterval(tick, 1000);
};

function submitResponse(index) {
    if (!GameUI.activeResponseRequest || GameUI.activeResponseRequest.expired) return;
    var request = GameUI.activeResponseRequest;
    GameUI.activeResponseRequest = null;
    clearInterval(GameUI.responseTimer);
    document.getElementById('responseModal').classList.remove('show');
    gameClient.playerAction({type: 'response', request_id: request.request_id, option_index: index}, []);
}

function submitMultiResponse() {
    if (!GameUI.activeResponseRequest || GameUI.activeResponseRequest.expired) return;
    var request = GameUI.activeResponseRequest;
    var indices = (GameUI.multiSelected || []).slice();
    GameUI.activeResponseRequest = null;
    GameUI.multiSelected = [];
    clearInterval(GameUI.responseTimer);
    document.getElementById('responseModal').classList.remove('show');
    gameClient.playerAction({type: 'response', request_id: request.request_id, option_indices: indices}, []);
}

gameClient.onStateUpdate = function (s) {
    GameUI.latestState = s;
    document.getElementById('rn').textContent = s.round;
    document.getElementById('dc').textContent = s.deck_count;
    document.getElementById('discardCount').textContent = s.discard_count || 0;
    document.getElementById('phaseText').textContent = s.phase || '进行中';
    document.getElementById('turnText').textContent = s.current_name + '的回合';

    var o = document.getElementById('opponents');
    o.innerHTML = '';
    s.players.forEach(function (p) {
        if (!p.hero_name || p.name === GameUI.playerName) return;
        var d = document.createElement('div');
        d.className = 'pl' + (p.alive ? '' : ' dead') + (p.name === s.current_name ? ' cur' : '');
        d.id = 'opp_' + p.id;
        var identity_label = '';
        if (p.identity_revealed && p.identity) {
            var id_map = {lord: '主', loyalist: '忠', rebel: '反', spy: '内'};
            identity_label = '<div style="position:absolute;top:2px;right:2px;background:#c41e3a;color:#fff;padding:2px 4px;border-radius:3px;font-size:9px;font-weight:bold">' + id_map[p.identity] + '</div>';
        }
        var hid = (p.hero && p.hero.id) || '';
        var hlabel = p.hero_name || p.name;
        d.innerHTML = identity_label +
            '<div class="av avatar-click" onclick="event.stopPropagation();openPlayerInfo(' + p.id + ')">' + heroImg(hid, hlabel) + '</div>' +
            '<div class="nm">' + p.name + '</div>' +
            '<div class="hp">' + '❤️'.repeat(Math.max(0, p.hp)) + '</div>' +
            '<div class="hc">' + p.hand_count + '张</div>' +
            (p.is_ai ? '<div class="gear" onclick="event.stopPropagation();openAISettings(' + p.id + ')">⚙</div>' : '');
        o.appendChild(d);
    });

    var me = s.players.find(function (p) { return p.name === GameUI.playerName; });
    if (me) {
        GameUI.myId = me.id;
        document.getElementById('myhp').textContent = '❤️'.repeat(Math.max(0, me.hp));
        document.getElementById('myhc').textContent = '手牌：' + me.hand_count + '张';
        var selfHeroId = (me.hero && me.hero.id) || (GameUI.hero && GameUI.hero.id) || '';
        var selfHeroName = (me.hero && me.hero.name) || me.hero_name || GameUI.playerName;
        document.getElementById('myav').innerHTML = heroImg(selfHeroId, selfHeroName);
        if (me.identity) {
            var id_text = {lord: '主公', loyalist: '忠臣', rebel: '反贼', spy: '内奸'}[me.identity];
            document.getElementById('myname').textContent = GameUI.playerName + ' (' + id_text + ')';
        }
    }
};

gameClient.onYourTurn = function (data) {
    L('⚔️ 你的回合！');
    GameUI.hand = data.hand || [];
    GameUI.availableActions = data.actions || [];
    GameUI.sel = null;
    GameUI.needTarget = false;
    GameUI.pendingAction = null;
    GameUI.selectedLegalAction = null;
    GameUI.targetSelection = [];
    document.getElementById('actionHint').style.display = 'block';
    document.getElementById('playBtn').textContent = '出牌';
    renderHand();
    updateButtons();
    audioManager.play('click');
};

gameClient.onActionResult = function (ok) {
    L(ok ? '✅' : '❌');
    if (!ok) {
        GameUI.sel = null;
        renderHand();
        updateButtons();
    }
};

gameClient.onChat = function (data) {
    L('💬 ' + data.from + ': ' + data.message, true);
    showSystemToast('[' + (data.from || 'AI') + '‘' + data.message + '’]');
};

gameClient.onEventNotification = function (data) {
    if (data.event_kind === 'card_to_discard' && data.card) {
        L('🃏 ' + (data.message || ((data.actor_name || '角色') + '使用【' + data.card.name + '】')));
        showSystemToast(data.system_text || ('【' + (data.actor_name || '角色') + '】' + data.card.name + '！'));
        enqueueCardAnimation(data);
    } else if (data.event_kind === 'skill_activation') {
        L('✨ ' + (data.message || ((data.actor_name || '角色') + '发动【' + data.skill_name + '】')));
        showSystemToast(data.system_text || ('[' + (data.actor_name || '角色') + '发动‘' + data.skill_name + '’]'));
    } else if (data.message) {
        L(data.message);
    }
};

gameClient.onError = function (data) {
    L('❌ ' + (data.message || '服务器错误'));
    document.getElementById('phaseText').textContent = '连接/游戏错误';
};

gameClient.onAIAction = function (data) {
    if (data.action === 'turn_start') {
        L('🤖 ' + data.player_name + '的回合');
    } else if (data.action === 'thinking_start') {
        if (!window.getGlobalSettings || getGlobalSettings().show_ai_thinking) L('🤔 ' + data.player_name + '正在思考...');
    } else if (data.action === 'thinking_end') {
        if (!window.getGlobalSettings || getGlobalSettings().show_ai_thinking) L('💡 ' + data.player_name + '思考摘要：' + (data.reasoning || '已选择合法操作'));
    } else if (data.action === 'use_card') {
        // 真实卡牌UI由服务端card_to_discard事件统一驱动。
    }
};

gameClient.onAIConfigUpdated = function () {
    showSystemToast('AI模型设置已更新');
    closeModal('aiSettingsModal');
};

gameClient.onEndGameAccepted = function () {
    showSystemToast('已请求结束对局，等待结算…');
};

gameClient.onGameEnd = function (data) {
    var state = data.state || GameUI.latestState || {};
    var me = (state.players || []).find(function (p) { return p.id === GameUI.myId; }) || {};
    var result = {
        winner: data.winner,
        message: data.message,
        total_rounds: state.round || 0,
        duration: data.duration || 0,
        player_identity: me.identity || '未知',
        player_won: data.winner === me.identity || (data.winner === 'lord' && (me.identity === 'lord' || me.identity === 'loyalist')),
        mvp: data.mvp || null,
        stats: data.stats || null,
        players: state.players || []
    };
    localStorage.setItem('gameResult', JSON.stringify(result));
    showSystemToast(data.message || '游戏结束');
    setTimeout(function () { location.href = 'result.html'; }, 700);
};

function renderHand() {
    var h = document.getElementById('hand');
    h.innerHTML = '';
    if (!GameUI.hand.length) {
        h.innerHTML = '<div style="padding:20px;color:var(--text-muted)">无手牌</div>';
        return;
    }
    GameUI.hand.forEach(function (c, i) {
        var d = document.createElement('div');
        d.className = 'card' + (GameUI.sel === i ? ' sel' : '');
        var suit = {spade: '♠', heart: '♥', club: '♣', diamond: '♦'}[c.suit] || '?';
        var col = ['heart', 'diamond'].includes(c.suit) ? 'r' : 'b';
        d.innerHTML = '<div class="cs ' + col + '">' + suit + c.rank + '</div><div class="cn">' + c.name + '</div>';
        d.onclick = (function (idx) {
            return function () {
                GameUI.sel = GameUI.sel === idx ? null : idx;
                checkNeedTarget(GameUI.sel);
                renderHand();
                updateButtons();
            };
        })(i);
        h.appendChild(d);
    });
}

function checkNeedTarget(idx) {
    GameUI.selectedLegalAction = GameUI.availableActions.find(function (a) {
        return a.type === 'play_card' && a.card_index === idx;
    }) || null;
    if (!GameUI.selectedLegalAction) {
        GameUI.needTarget = false;
        GameUI.pendingAction = null;
        GameUI.targetSelection = [];
        document.getElementById('actionHint').textContent = '🚫 当前不能使用此牌';
        highlightTargets(false, []);
        return;
    }
    GameUI.needTarget = !!GameUI.selectedLegalAction.requires_target;
    GameUI.targetSelection = [];
    if (GameUI.needTarget) {
        document.getElementById('actionHint').textContent = GameUI.selectedLegalAction.target_count === 2
            ? '👆 先选择持有武器的角色，再选择攻击目标'
            : '👆 点击绿色目标';
        highlightTargets(true, GameUI.selectedLegalAction.valid_targets || []);
    } else {
        document.getElementById('actionHint').textContent = '👆 点击出牌';
        highlightTargets(false, []);
    }
}

function highlightTargets(on, validIds) {
    validIds = validIds || [];
    document.querySelectorAll('.pl').forEach(function (p) {
        var pid = parseInt(p.id.replace('opp_', ''));
        if (on && validIds.includes(pid) && !p.classList.contains('dead')) {
            p.classList.add('targetable');
            p.onclick = function () { selectTarget(pid); };
        } else {
            p.classList.remove('targetable');
            p.onclick = null;
        }
    });
}

function selectTarget(tid) {
    tid = parseInt(tid);
    if (!GameUI.selectedLegalAction || !(GameUI.selectedLegalAction.valid_targets || []).includes(tid)) {
        L('❌ 非法目标');
        return;
    }

    if (GameUI.selectedLegalAction.target_count === 2) {
        var pair = GameUI.targetSelection || [];
        if (pair.length === 0) {
            var firstPairs = (GameUI.selectedLegalAction.valid_target_pairs || []).filter(function (p) { return p[0] === tid; });
            if (!firstPairs.length) {
                L('❌ 请选择有武器的角色');
                return;
            }
            GameUI.targetSelection = [tid];
            highlightTargets(true, firstPairs.map(function (p) { return p[1]; }));
            document.querySelectorAll('.pl.chosen').forEach(function (p) { p.classList.remove('chosen'); });
            var first = document.getElementById('opp_' + tid);
            if (first) first.classList.add('chosen');
            document.getElementById('actionHint').textContent = '👆 请选择该角色要攻击的目标';
            return;
        }
        var candidate = [pair[0], tid];
        var validPair = (GameUI.selectedLegalAction.valid_target_pairs || []).some(function (p) {
            return p[0] === candidate[0] && p[1] === candidate[1];
        });
        if (!validPair) {
            L('❌ 该攻击目标不在武器范围内');
            return;
        }
        GameUI.targetSelection = candidate;
    } else {
        GameUI.targetSelection = [tid];
    }

    if (GameUI.selectedLegalAction.type === 'use_skill') {
        GameUI.pendingAction = Object.assign({}, GameUI.selectedLegalAction, {target_ids: GameUI.targetSelection.slice()});
    } else {
        GameUI.pendingAction = {type: 'play_card', card_index: GameUI.sel, target_ids: GameUI.targetSelection.slice()};
    }
    highlightTargets(false, []);
    document.querySelectorAll('.pl.chosen').forEach(function (p) { p.classList.remove('chosen'); });
    GameUI.targetSelection.forEach(function (id) {
        var target = document.getElementById('opp_' + id);
        if (target) target.classList.add('chosen');
    });
    L('已选择目标');
    updateButtons();
}

function updateButtons() {
    var isSkill = GameUI.selectedLegalAction && GameUI.selectedLegalAction.type === 'use_skill';
    var hasSel = GameUI.sel !== null || isSkill;
    var needsTarget = hasSel && GameUI.needTarget && !GameUI.pendingAction;
    document.getElementById('playBtn').disabled = !hasSel || !GameUI.selectedLegalAction || needsTarget;
    document.getElementById('endBtn').disabled = false;
}

function showSystemToast(text) {
    if (!text) return;
    var box = document.getElementById('systemToasts');
    var toast = document.createElement('div');
    toast.className = 'system-toast';
    toast.textContent = text;
    box.appendChild(toast);
    setTimeout(function () {
        toast.style.opacity = '0';
        setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 180);
    }, 1000);
}

function closeModal(id) {
    document.getElementById(id).classList.remove('show');
}

function skillHTML(skills) {
    if (!skills || !skills.length) return '<div class="skill-entry">暂无技能数据</div>';
    return skills.map(function (skill) {
        var name = typeof skill === 'string' ? skill : (skill.name || '未命名技能');
        var desc = typeof skill === 'string' ? '' : (skill.description || skill.detail || '技能逻辑尚未接入，当前仅展示数据。');
        var type = typeof skill === 'string' ? '' : (skill.type || skill.trigger_event || '');
        return '<div class="skill-entry"><b>【' + name + '】</b> ' + (type ? '<small>' + type + '</small><br>' : '') + desc + '</div>';
    }).join('');
}

function openPlayerInfo(playerId) {
    if (!GameUI.latestState) return;
    var p = GameUI.latestState.players.find(function (x) { return x.id === playerId; });
    if (!p) return;
    document.getElementById('playerInfoTitle').textContent = p.name + ' · ' + (p.hero_name || '未知武将');
    var identity = p.identity ? ({lord: '主公', loyalist: '忠臣', rebel: '反贼', spy: '内奸'}[p.identity] || p.identity) : '未公开';
    document.getElementById('playerInfoBody').innerHTML =
        '<p>势力：' + ((p.hero || {}).faction || '未知') + '　体力：' + p.hp + '/' + p.max_hp + '　身份：' + identity + '</p>' +
        '<p style="margin-top:8px;color:#aaa">手牌：' + p.hand_count + '张　装备：' + Object.values(p.equipment || {}).join('、') + '</p>' +
        '<h4 style="margin-top:14px;color:var(--gold)">武将技能</h4>' + skillHTML((p.hero || {}).skills) +
        (p.is_ai ? '<div class="modal-actions"><button onclick="closeModal(&quot;playerInfoModal&quot;);openAISettings(' + p.id + ')">⚙ 调整该AI模型</button></div>' : '');
    document.getElementById('playerInfoModal').classList.add('show');
}

function showMySkills() {
    if (GameUI.myId === null) { showSystemToast('游戏尚未初始化'); return; }
    if (!GameUI.latestState) return;
    var p = GameUI.latestState.players.find(function (x) { return x.id === GameUI.myId; });
    if (!p) return;
    var legal = GameUI.availableActions.filter(function (a) { return a.type === 'use_skill'; });
    document.getElementById('playerInfoTitle').textContent = p.name + ' · 技能';
    document.getElementById('playerInfoBody').innerHTML =
        '<h4 style="color:var(--gold)">武将技能</h4>' + skillHTML((p.hero || {}).skills) +
        '<h4 style="margin-top:14px;color:#7dff9c">当前合法技能操作</h4>' +
        (legal.length ? legal.map(function (a, i) {
            var cards = (a.card_indices || []).map(function (idx) { return GameUI.hand[idx] ? GameUI.hand[idx].name : '#' + idx; }).join('、');
            return '<div class="skill-entry"><b>【' + a.skill_name + '】</b> ' + (a.description || a.variant || '') +
                (cards ? '<br><small>消耗：' + cards + '</small>' : '') +
                '<div class="modal-actions"><button onclick="chooseSkillAction(' + i + ')">发动</button></div></div>';
        }).join('') : '<div class="skill-entry">当前阶段没有可主动发动的技能；锁定技和触发技由引擎自动结算。</div>');
    document.getElementById('playerInfoModal').dataset.skillActions = JSON.stringify(legal);
    document.getElementById('playerInfoModal').classList.add('show');
}

function chooseSkillAction(index) {
    var actions = JSON.parse(document.getElementById('playerInfoModal').dataset.skillActions || '[]');
    var action = actions[index];
    if (!action) return;
    closeModal('playerInfoModal');
    GameUI.sel = null;
    GameUI.selectedLegalAction = action;
    GameUI.pendingAction = null;
    GameUI.needTarget = !!action.requires_target;
    if (GameUI.needTarget) {
        document.getElementById('actionHint').style.display = 'block';
        document.getElementById('actionHint').textContent = '👆 为【' + action.skill_name + '】选择绿色目标';
        highlightTargets(true, action.valid_targets || []);
        document.getElementById('playBtn').textContent = '发动';
        updateButtons();
    } else {
        L('发动【' + action.skill_name + '】');
        gameClient.playerAction(action, []);
        document.getElementById('playBtn').textContent = '出牌';
    }
}

function fillAiSettingProvider() {
    var sel = document.getElementById('aiSettingProvider');
    if (!sel) return;
    var list = (GameUI.aiSettingProviderList && GameUI.aiSettingProviderList.length)
        ? GameUI.aiSettingProviderList
        : (window.Protocol ? Protocol.PROVIDERS : []);
    sel.innerHTML = list.map(function (p) { return '<option value="' + p.value + '">' + p.name + '</option>'; }).join('');
}

function loadAiSettingProviders() {
    fetch('/api/providers', {cache: 'no-store'})
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d && d.providers && d.providers.length) {
                GameUI.aiSettingProviderList = d.providers;
                fillAiSettingProvider();
            }
        })
        .catch(function () {});
}

function openAISettings(playerId) {
    if (!GameUI.latestState) return;
    var p = GameUI.latestState.players.find(function (x) { return x.id === playerId; });
    if (!p || !p.is_ai) return;
    fillAiSettingProvider();
    var c = p.ai_config || {};
    document.getElementById('aiSettingsTitle').textContent = p.name + ' · AI模型设置';
    document.getElementById('aiSettingPlayerId').value = p.id;
    document.getElementById('aiSettingProvider').value = c.provider || (GameUI.aiSettingProviderList && GameUI.aiSettingProviderList[0]
        ? GameUI.aiSettingProviderList[0].value
        : (window.Protocol ? Protocol.PROVIDERS[0].value : 'deepseek'));
    document.getElementById('aiSettingModel').value = c.model || 'deepseek-chat';
    document.getElementById('aiSettingUrl').value = c.api_url || '';
    document.getElementById('aiSettingKey').value = '';
    document.getElementById('aiSettingTemperature').value = c.temperature === undefined ? 0.8 : c.temperature;
    document.getElementById('aiSettingThinking').checked = !!c.thinking;
    document.getElementById('aiSettingsModal').classList.add('show');
}

function saveAISettings() {
    gameClient.send({
        type: Protocol.INBOUND.UPDATE_AI_CONFIG,
        player_id: parseInt(document.getElementById('aiSettingPlayerId').value),
        config: {
            provider: document.getElementById('aiSettingProvider').value,
            model: document.getElementById('aiSettingModel').value.trim(),
            api_url: document.getElementById('aiSettingUrl').value.trim(),
            api_key: document.getElementById('aiSettingKey').value.trim(),
            temperature: parseFloat(document.getElementById('aiSettingTemperature').value),
            thinking: document.getElementById('aiSettingThinking').checked
        }
    });
}

function doEndGame() {
    if (!confirm('确定结束本局游戏吗？本局将记为主动终止。')) return;
    document.getElementById('quitBtn').disabled = true;
    gameClient.send({type: Protocol.INBOUND.END_GAME, reason: '玩家主动结束游戏'});
}

function doPlay() {
    var act, tids = [];
    if (GameUI.pendingAction) {
        tids = GameUI.pendingAction.target_ids || [];
        if (GameUI.pendingAction.type === 'use_skill') act = Object.assign({}, GameUI.pendingAction);
        else act = {type: 'play_card', card_index: GameUI.pendingAction.card_index};
    } else if (GameUI.sel !== null) {
        act = {type: 'play_card', card_index: GameUI.sel};
    } else return;

    var card = Number.isInteger(act.card_index) ? GameUI.hand[act.card_index] : null;
    if (card) L('提交使用【' + card.name + '】');
    if (act.type === 'use_skill') L('提交发动【' + act.skill_name + '】');
    gameClient.playerAction(act, tids);
    GameUI.sel = null;
    GameUI.pendingAction = null;
    GameUI.needTarget = false;
    GameUI.selectedLegalAction = null;
    GameUI.targetSelection = [];
    highlightTargets(false, []);
    document.querySelectorAll('.pl.chosen').forEach(function (p) { p.classList.remove('chosen'); });
    document.getElementById('playBtn').disabled = true;
    document.getElementById('playBtn').textContent = '出牌';
}

function doEnd() {
    L('结束阶段');
    gameClient.playerAction({type: 'end_phase'});
    GameUI.sel = null;
    GameUI.hand = [];
    renderHand();
    document.getElementById('playBtn').disabled = true;
    document.getElementById('playBtn').textContent = '出牌';
    document.getElementById('endBtn').disabled = true;
    document.getElementById('actionHint').style.display = 'none';
    highlightTargets(false, []);
    document.querySelectorAll('.pl.chosen').forEach(function (p) { p.classList.remove('chosen'); });
}

function toggleLog() {
    var logWrap = document.getElementById('logWrap');
    var btn = document.getElementById('logToggle');
    if (logWrap.classList.contains('expanded')) {
        logWrap.classList.remove('expanded');
        btn.textContent = '▼';
    } else {
        logWrap.classList.add('expanded');
        btn.textContent = '▲';
    }
}

function updateLogPosition() {
    var myarea = document.getElementById('myarea');
    if (!myarea) return;
    var rect = myarea.getBoundingClientRect();
    var logWrap = document.getElementById('logWrap');
    logWrap.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
}

window.doPlay = doPlay;
window.doEnd = doEnd;
window.doEndGame = doEndGame;
window.showMySkills = showMySkills;
window.openPlayerInfo = openPlayerInfo;
window.openAISettings = openAISettings;
window.saveAISettings = saveAISettings;
window.closeModal = closeModal;
window.toggleLog = toggleLog;
window.chooseSkillAction = chooseSkillAction;

if (!configIsLegal(GameUI.gameConfig)) {
    rejectBadConfig('对局配置不完整，请从大厅重新开始。');
} else {
    gameClient.connect();
    loadAiSettingProviders();
    window.addEventListener('resize', updateLogPosition);
    window.addEventListener('orientationchange', updateLogPosition);
    setTimeout(updateLogPosition, 100);
    L('连接中...');
}
