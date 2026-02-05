/**
 * Celebrations & Motivation System
 * Confetti effects, XP notifications, level-up displays, Polish encouragements
 */
const CELEBRATIONS = {
    // Polish encouragements by context
    encouragements: {
        xp: [
            "Swietnie!", "Brawo!", "Tak trzymaj!", "Niesamowicie!",
            "Super robota!", "Jestes wspanialy!", "Fantastycznie!"
        ],
        levelUp: [
            "Nowy poziom! Gratulacje!",
            "Awans! Ruszasz do przodu!",
            "Jestes coraz lepszy!",
            "Niesamowity postep!"
        ],
        streak: [
            "Seria trwa!", "Nie zatrzymuj sie!",
            "Codziennie lepiej!", "Konsekwencja popyla!"
        ],
        perfect: [
            "PERFEKCYJNIE!", "Idealny wynik!",
            "Bez bledow! Niesamowite!", "100% - Mistrz!"
        ],
        comeback: [
            "Witaj z powrotem!", "Dobrze Cie widziec!",
            "Kazdy dzien to nowy poczatek!", "Nie poddawaj sie!"
        ],
        game: [
            "Dobra gra!", "Swietny wynik!",
            "Grasz coraz lepiej!", "Mistrzowska rozgrywka!"
        ]
    },

    getRandomEncouragement(type) {
        const list = this.encouragements[type] || this.encouragements.xp;
        return list[Math.floor(Math.random() * list.length)];
    },

    showXpGain(amount) {
        const notification = document.createElement('div');
        notification.className = 'xp-notification';
        notification.innerHTML = `
            <span class="xp-gain-amount">+${amount} XP</span>
            <span class="xp-gain-text">${this.getRandomEncouragement('xp')}</span>
        `;
        document.body.appendChild(notification);

        requestAnimationFrame(() => notification.classList.add('show'));

        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 500);
        }, 2500);
    },

    showLevelUp(newLevel) {
        const overlay = document.createElement('div');
        overlay.className = 'level-up-overlay';
        overlay.innerHTML = `
            <div class="level-up-card">
                <div class="level-up-badge">${newLevel}</div>
                <h2>Level Up!</h2>
                <p>${this.getRandomEncouragement('levelUp')}</p>
                <button onclick="this.parentElement.parentElement.remove()" class="btn btn-primary">OK!</button>
            </div>
        `;
        document.body.appendChild(overlay);

        this.triggerConfetti();

        setTimeout(() => overlay.remove(), 8000);
    },

    showStreakCelebration(streakDays) {
        const notification = document.createElement('div');
        notification.className = 'streak-notification';
        notification.innerHTML = `
            <span class="streak-fire">!</span>
            <span>${streakDays}-day streak! ${this.getRandomEncouragement('streak')}</span>
        `;
        document.body.appendChild(notification);

        requestAnimationFrame(() => notification.classList.add('show'));
        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 500);
        }, 3000);
    },

    showAchievement(achievement) {
        const notification = document.createElement('div');
        notification.className = 'achievement-notification';
        notification.innerHTML = `
            <div class="ach-notif-icon">${achievement.icon || '?'}</div>
            <div class="ach-notif-info">
                <div class="ach-notif-label">Achievement Unlocked!</div>
                <div class="ach-notif-title">${achievement.title}</div>
                <div class="ach-notif-title-pl">${achievement.title_pl || ''}</div>
                ${achievement.xp_reward ? `<div class="ach-notif-xp">+${achievement.xp_reward} XP</div>` : ''}
            </div>
        `;
        document.body.appendChild(notification);

        requestAnimationFrame(() => notification.classList.add('show'));
        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 500);
        }, 4000);
    },

    triggerConfetti() {
        const canvas = document.createElement('canvas');
        canvas.className = 'confetti-canvas';
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        document.body.appendChild(canvas);

        const ctx = canvas.getContext('2d');
        const particles = [];
        const colors = ['#3498db', '#2ecc71', '#e74c3c', '#f1c40f', '#9b59b6', '#e67e22'];

        for (let i = 0; i < 100; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: -20 - Math.random() * 100,
                w: 5 + Math.random() * 8,
                h: 3 + Math.random() * 5,
                color: colors[Math.floor(Math.random() * colors.length)],
                vx: (Math.random() - 0.5) * 4,
                vy: 2 + Math.random() * 4,
                rotation: Math.random() * 360,
                rotationSpeed: (Math.random() - 0.5) * 10,
            });
        }

        let frame = 0;
        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            for (const p of particles) {
                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate(p.rotation * Math.PI / 180);
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
                ctx.restore();

                p.x += p.vx;
                p.y += p.vy;
                p.vy += 0.05;
                p.rotation += p.rotationSpeed;
            }

            frame++;
            if (frame < 120) {
                requestAnimationFrame(animate);
            } else {
                canvas.remove();
            }
        }

        animate();
    },

    // Process XP/achievement results from API responses
    processResult(result) {
        if (!result) return;

        if (result.xp_gained) {
            this.showXpGain(result.xp_gained);
        }
        if (result.leveled_up) {
            setTimeout(() => this.showLevelUp(result.level), 800);
        }
        if (result.new_achievements) {
            result.new_achievements.forEach((ach, i) => {
                setTimeout(() => this.showAchievement(ach), 1500 + i * 1200);
            });
        }
    }
};
