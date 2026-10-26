-- Ejecutar en Supabase → SQL Editor (una vez, al crear el proyecto).

-- 1. Tabla mínima que el pipeline diario consulta para que el proyecto gratuito no se pause
--    (Supabase pausa los proyectos gratuitos tras 7 días sin actividad).
create table if not exists public.heartbeat (id int primary key, note text);
insert into public.heartbeat values (1, 'ping diario del pipeline') on conflict do nothing;
alter table public.heartbeat enable row level security;
drop policy if exists "heartbeat legible" on public.heartbeat;
create policy "heartbeat legible" on public.heartbeat for select to anon, authenticated using (true);

-- 2. Administradores: el rol viaja en el token (app_metadata) y la API lo revisa (app/auth.py).
--    Cambia el correo y repite para cada administrador. El usuario debe volver a iniciar sesión.
update auth.users
   set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role": "admin"}'
 where email = 'jjosuefong@gmail.com';
