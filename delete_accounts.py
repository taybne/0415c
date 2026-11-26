#!/usr/bin/env python
"""Delete accounts by nickname: python delete_accounts.py nick1 nick2 ..."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, User, PrivateMessage, SavedLocation, FavoriteLocation, FriendRequest


def delete_account_by_nickname(nickname):
    with app.app_context():
        user = User.query.filter_by(nickname=nickname).first()
        if not user:
            print(f"Not found: {nickname}")
            return False
        uid = user.id
        PrivateMessage.query.filter((PrivateMessage.sender_id == uid) | (PrivateMessage.receiver_id == uid)).delete(synchronize_session=False)
        FriendRequest.query.filter((FriendRequest.sender_id == uid) | (FriendRequest.receiver_id == uid)).delete(synchronize_session=False)
        SavedLocation.query.filter_by(user_id=uid).delete(synchronize_session=False)
        FavoriteLocation.query.filter_by(user_id=uid).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()
        print(f"Deleted: {nickname}")
        return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python delete_accounts.py <nickname> [<nickname> ...]")
        sys.exit(1)
    for n in sys.argv[1:]:
        delete_account_by_nickname(n)
