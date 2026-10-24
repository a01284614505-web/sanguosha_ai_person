// 闪电判定标记的电光效果（批次 2）。
// 用户要求做成可切换：全局设置里的 bolt_style 决定样式——
//   arc       电弧跳动：几道分叉电弧从菱形里往外乱窜
//   particle  电粒子环绕：一圈电粒子绕着菱形转，偶尔劈出一道细电弧
//   mix       电弧 + 粒子（默认）
//   off       关闭，只保留菱形本身
// 做法：给每个 .judge-tile.thunder 塞一块 canvas，全页只跑一个动画循环（约 15 帧/秒，够看又省电）；
// 页面切到后台、系统开启"减少动态效果"时停下。
(function (global) {
    'use strict';

    const FPS_GAP = 66;
    const reduce = () => global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const style = () => {
        const s = global.getGlobalSettings ? global.getGlobalSettings() : {};
        return ['arc', 'particle', 'mix', 'off'].includes(s.bolt_style) ? s.bolt_style : 'mix';
    };

    /** 递归中点位移画一道分叉电弧（经典闪电算法），depth 控制折线段数。 */
    function zig(ctx, x1, y1, x2, y2, spread, depth) {
        if (depth <= 0 || Math.hypot(x2 - x1, y2 - y1) < 3) { ctx.lineTo(x2, y2); return; }
        const mx = (x1 + x2) / 2 + (Math.random() - 0.5) * spread;
        const my = (y1 + y2) / 2 + (Math.random() - 0.5) * spread;
        zig(ctx, x1, y1, mx, my, spread / 2, depth - 1);
        zig(ctx, mx, my, x2, y2, spread / 2, depth - 1);
    }

    function stroke2(ctx, w) {
        ctx.strokeStyle = 'rgba(150,130,255,.55)'; ctx.lineWidth = w * 0.035; ctx.stroke();
        ctx.strokeStyle = 'rgba(238,242,255,.95)'; ctx.lineWidth = w * 0.012; ctx.stroke();
    }

    function draw(cv, mode, t) {
        const ctx = cv.getContext('2d');
        const W = cv.width, H = cv.height, cx = W / 2, cy = H / 2, R = W * 0.2;
        ctx.clearRect(0, 0, W, H);
        if (mode === 'off') return;
        ctx.globalCompositeOperation = 'lighter';
        const flick = 0.6 + 0.4 * Math.sin(t / 90) * Math.sin(t / 37);
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, W * 0.48);
        g.addColorStop(0, 'rgba(170,150,255,' + (0.32 * flick) + ')');
        g.addColorStop(1, 'rgba(90,60,200,0)');
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
        if (mode === 'arc' || mode === 'mix') {
            const n = mode === 'arc' ? 3 : 2;
            for (let k = 0; k < n; k++) {
                if (mode === 'mix' && Math.random() < 0.35) continue;
                const a = Math.random() * Math.PI * 2, r2 = W * (0.32 + Math.random() * 0.12);
                const sx = cx + Math.cos(a) * R * 0.6, sy = cy + Math.sin(a) * R * 0.6;
                ctx.beginPath(); ctx.moveTo(sx, sy);
                zig(ctx, sx, sy, cx + Math.cos(a + 0.5) * r2, cy + Math.sin(a + 0.5) * r2, W * 0.18, 5);
                stroke2(ctx, W);
            }
        }
        if (mode === 'particle' || mode === 'mix') {
            const n = mode === 'particle' ? 22 : 14;
            for (let i = 0; i < n; i++) {
                const a = t / (380 + i * 23) + i * 2.4, rr = R * (1.1 + 0.45 * Math.sin(t / 260 + i));
                const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr * 0.92, s = W * (0.012 + 0.012 * ((i * 7) % 3));
                ctx.fillStyle = 'rgba(210,220,255,.9)'; ctx.beginPath(); ctx.arc(x, y, s, 0, 7); ctx.fill();
                ctx.strokeStyle = 'rgba(140,120,255,.45)'; ctx.lineWidth = s * 0.9;
                ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(cx + Math.cos(a - 0.25) * rr, cy + Math.sin(a - 0.25) * rr * 0.92); ctx.stroke();
            }
            if (Math.random() < 0.18) {
                const a = Math.random() * 7;
                ctx.beginPath(); ctx.moveTo(cx, cy);
                zig(ctx, cx, cy, cx + Math.cos(a) * R * 1.5, cy + Math.sin(a) * R * 1.5, W * 0.1, 4);
                ctx.strokeStyle = 'rgba(240,244,255,.9)'; ctx.lineWidth = W * 0.01; ctx.stroke();
            }
        }
        ctx.globalCompositeOperation = 'source-over';
    }

    /** 给还没有 canvas 的闪电标记补一块（标记会随座位重绘而重建，所以每帧检查一次）。 */
    function ensureCanvas(tile) {
        let cv = tile.querySelector('canvas.bolt-fx');
        if (!cv) {
            cv = document.createElement('canvas');
            cv.className = 'bolt-fx';
            cv.width = 128; cv.height = 128;
            cv.setAttribute('aria-hidden', 'true');
            tile.appendChild(cv);
        }
        return cv;
    }

    let raf = 0, last = 0;
    function frame(t) {
        raf = 0;
        if (document.hidden) return;
        const tiles = document.querySelectorAll('.judge-tile.thunder');
        const mode = style();
        document.documentElement.dataset.bolt = mode;
        if (t - last >= FPS_GAP) {
            last = t;
            tiles.forEach(tile => draw(ensureCanvas(tile), mode, t));
        }
        // 减少动态效果：画一帧静态的就停；没有闪电标记时低频轮询，有了再动起来
        if (reduce() || mode === 'off') { setTimeout(start, 1500); return; }
        if (tiles.length) raf = requestAnimationFrame(frame);
        else setTimeout(start, 800);
    }
    function start() { if (!raf) raf = requestAnimationFrame(frame); }

    document.addEventListener('visibilitychange', () => { if (!document.hidden) start(); });
    global.addEventListener('global-settings-changed', start);
    global.BoltFX = { start: start, draw: draw };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(window);
