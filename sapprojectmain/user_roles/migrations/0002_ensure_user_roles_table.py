from django.db import migrations


def ensure_user_roles_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_roles (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                assigned_by_id uuid NULL REFERENCES users(id) ON DELETE SET NULL,
                assigned_at timestamp with time zone NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS unique_user_role_assignment
            ON user_roles(user_id, role_id);
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS user_roles_user_id_idx
            ON user_roles(user_id);
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS user_roles_role_id_idx
            ON user_roles(role_id);
            """
        )


def seed_default_reader_for_existing_users(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id FROM roles WHERE role_name = 'reader' LIMIT 1;")
        row = cursor.fetchone()
        if not row:
            return
        reader_role_id = row[0]
        cursor.execute(
            """
            INSERT INTO user_roles (id, user_id, role_id, assigned_by_id, assigned_at)
            SELECT gen_random_uuid(), u.id, %s, NULL, NOW()
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.id AND ur.role_id = %s
            WHERE ur.id IS NULL;
            """,
            [reader_role_id, reader_role_id],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("user_roles", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(ensure_user_roles_table, migrations.RunPython.noop),
        migrations.RunPython(
            seed_default_reader_for_existing_users, migrations.RunPython.noop
        ),
    ]
