-- Additive review-only metadata; canonical identifiers and existing relationships remain intact.
ALTER TABLE categories ADD COLUMN admin_managed INTEGER NOT NULL DEFAULT 0 CHECK (admin_managed IN (0,1));
ALTER TABLE categories ADD COLUMN admin_row_version INTEGER NOT NULL DEFAULT 1 CHECK (admin_row_version>0);
CREATE TRIGGER categories_admin_revision AFTER UPDATE OF name_fa,parent_id,sort_order,level,admin_managed ON categories
WHEN OLD.name_fa IS NOT NEW.name_fa OR OLD.parent_id IS NOT NEW.parent_id OR OLD.sort_order IS NOT NEW.sort_order OR OLD.level IS NOT NEW.level OR OLD.admin_managed IS NOT NEW.admin_managed
BEGIN
 UPDATE categories SET admin_row_version=OLD.admin_row_version+1 WHERE id=NEW.id;
END;
