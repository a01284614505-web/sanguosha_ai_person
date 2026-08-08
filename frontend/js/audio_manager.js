// 音效管理器 - AudioManager
class AudioManager {
    constructor() {
        this.sounds = new Map();
        this.bgm = null;
        this.volume = {
            master: 1.0,
            bgm: 0.7,
            effect: 0.8,
            voice: 1.0
        };
        this.enabled = true;
        this.init();
    }

    init() {
        // 预加载关键音效
        this.preloadSounds([
            'button_click',
            'card_flip',
            'card_play',
            'damage',
            'heal'
        ]);
    }

    preloadSounds(soundNames) {
        soundNames.forEach(name => {
            const audio = new Audio();
            audio.preload = 'auto';
            // 音效文件路径（当前使用占位符）
            audio.src = `sounds/${name}.mp3`;
            audio.onerror = () => {
                console.warn(`音效加载失败: ${name}`);
            };
            this.sounds.set(name, audio);
        });
    }

    play(soundName, category = 'effect') {
        if (!this.enabled) return;

        let audio = this.sounds.get(soundName);
        
        if (!audio) {
            // 动态加载
            audio = new Audio(`sounds/${soundName}.mp3`);
            this.sounds.set(soundName, audio);
        }

        // 克隆音频以支持重叠播放
        const sound = audio.cloneNode();
        sound.volume = this.volume.master * this.volume[category];
        
        sound.play().catch(err => {
            console.warn(`音效播放失败: ${soundName}`, err);
        });

        return sound;
    }

    playBGM(bgmName) {
        // 停止当前BGM
        this.stopBGM();

        this.bgm = new Audio(`sounds/bgm/${bgmName}.mp3`);
        this.bgm.volume = this.volume.master * this.volume.bgm;
        this.bgm.loop = true;
        
        this.bgm.play().catch(err => {
            console.warn(`BGM播放失败: ${bgmName}`, err);
        });
    }

    stopBGM() {
        if (this.bgm) {
            this.bgm.pause();
            this.bgm.currentTime = 0;
            this.bgm = null;
        }
    }

    setVolume(category, value) {
        this.volume[category] = Math.max(0, Math.min(1, value));
        
        if (category === 'bgm' && this.bgm) {
            this.bgm.volume = this.volume.master * this.volume.bgm;
        }
    }

    toggle() {
        this.enabled = !this.enabled;
        if (!this.enabled) {
            this.stopBGM();
        }
    }

    // 快捷方法
    playCardSound(cardName) {
        this.play(`card_${cardName.toLowerCase()}`);
    }

    playSkillSound(heroId, skillName) {
        this.play(`${heroId}_${skillName}`, 'voice');
    }

    playUISound(action) {
        const soundMap = {
            'click': 'button_click',
            'hover': 'button_hover',
            'draw': 'card_draw',
            'flip': 'card_flip',
            'play': 'card_play',
            'alert': 'alert',
            'success': 'success',
            'error': 'error'
        };
        
        const soundName = soundMap[action] || action;
        this.play(soundName, 'effect');
    }

    playGameSound(event) {
        const soundMap = {
            'damage': 'damage',
            'heal': 'heal',
            'death': 'death',
            'win': 'win',
            'lose': 'lose',
            'judge': 'judge',
            'shuffle': 'shuffle',
            'phase': 'phase_change'
        };
        
        const soundName = soundMap[event] || event;
        this.play(soundName, 'effect');
    }
}

// 全局音效管理器实例
const audioManager = new AudioManager();

// 绑定UI事件
document.addEventListener('DOMContentLoaded', () => {
    // 按钮点击音效
    document.querySelectorAll('button, .btn, .clickable').forEach(element => {
        element.addEventListener('click', () => {
            audioManager.playUISound('click');
        });
    });

    // 播放背景音乐
    audioManager.playBGM('game');
});
