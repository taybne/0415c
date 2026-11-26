# Telegram Bot Configuration for TAG App

## Настройка Telegram бота для верификации

### 1. Создайте бота в Telegram
Перейдите к [@BotFather](https://t.me/botfather) в Telegram.

### 2. Создайте нового бота
- Отправьте команду `/newbot`
- Введите имя бота (например, "TAG Verification Bot")
- Введите username бота (например, "tag_verification_bot")
- Скопируйте токен бота

### 3. Настройте переменные окружения

Создайте файл `.env` в папке `miniapp/` (или добавьте к существующему):

```
TELEGRAM_BOT_TOKEN=your-bot-token-here
```

### 4. Запустите бота

Запустите бота отдельно:

```bash
cd bot
python bot.py
```

Или в фоне:

```bash
python bot.py &
```

### 5. Тестирование

1. Перейдите на http://127.0.0.1:5000/register
2. Введите nickname
3. Нажмите "Register"
4. Напишите боту `/verify ваш_никнейм`
5. Введите код на сайте

## Команды бота

- `/start` - Приветствие
- `/verify никнейм` - Получить код верификации

## Альтернативные сервисы

Если Gmail не подходит, можно использовать:

- **Yandex.Mail**: smtp.yandex.ru, порт 587
- **Mail.ru**: smtp.mail.ru, порт 587
- **SendGrid**: smtp.sendgrid.com, порт 587
- **Mailgun**: smtp.mailgun.org, порт 587

## Безопасность

- Никогда не храните пароли в коде
- Используйте App Passwords вместо основных паролей
- Для продакшена используйте специализированные сервисы (SendGrid, Mailgun)