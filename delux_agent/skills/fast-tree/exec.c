#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>

void print_tree(const char *path, int indent, int is_last) {
    DIR *dir = opendir(path);
    if (!dir) return;

    struct dirent *entry;
    struct dirent **entries = NULL;
    int count = 0;

    // Count and store entries
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0 || 
            entry->d_name[0] == '.' || strcmp(entry->d_name, "node_modules") == 0) continue;
        
        entries = realloc(entries, sizeof(struct dirent *) * (count + 1));
        entries[count] = malloc(sizeof(struct dirent));
        memcpy(entries[count], entry, sizeof(struct dirent));
        count++;
    }
    closedir(dir);

    for (int i = 0; i < count; i++) {
        for (int j = 0; j < indent; j++) printf("│   ");
        
        int last_entry = (i == count - 1);
        printf("%s── ", last_entry ? "└──" : "├──");

        struct stat st;
        char full_path[1024];
        snprintf(full_path, sizeof(full_path), "%s/%s", path, entries[i]->d_name);
        stat(full_path, &st);

        if (S_ISDIR(st.st_mode)) {
            printf("\033[1;34m%s/\033[0m\n", entries[i]->d_name);
            print_tree(full_path, indent + 1, last_entry);
        } else {
            printf("%s\n", entries[i]->d_name);
        }
        free(entries[i]);
    }
    free(entries);
}

int main() {
    printf("\033[1;36m. (Project Root)\033[0m\n");
    print_tree(".", 0, 1);
    return 0;
}
