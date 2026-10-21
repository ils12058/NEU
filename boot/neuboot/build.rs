fn main() {
    println!("cargo::rerun-if-changed=build.rs");

    if std::env::var("PROFILE").is_ok_and(|profile| profile == "release") {
        // rustc enables PDB generation for PE images even without debug info.
        // Its embedded identifier varies between links; release needs no PDB.
        println!("cargo::rustc-link-arg-bin=neuboot=/DEBUG:NONE");
    }
}
